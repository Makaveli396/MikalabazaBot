import asyncio
import logging
import re
from difflib import SequenceMatcher
from datetime import datetime
import aiohttp
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== CONFIGURACIÓN - TOKENS CONFIGURADOS ==========
TELEGRAM_TOKEN = "7557935323:AAFtEmvBqemYLZzljjjpyBUBRrsd3AArOoU"
TMDB_API_KEY = "17bb8342bff5717c23c85b661d8bb512"
OMDB_API_KEY = "8db71856"

# URLs de las APIs
TMDB_BASE_URL = "https://api.themoviedb.org/3"
OMDB_BASE_URL = "http://www.omdbapi.com"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

class MovieBot:
    def __init__(self):
        self.session = None
    
    async def init_session(self):
        """Inicializa la sesión HTTP"""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close_session(self):
        """Cierra la sesión HTTP"""
        if self.session:
            await self.session.close()
    
    def similarity(self, a, b):
        """Calcula similitud entre dos strings"""
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()
    
    async def search_tmdb(self, query, media_type="multi"):
        """Busca en TMDB con tolerancia a errores"""
        await self.init_session()
        
        url = f"{TMDB_BASE_URL}/search/{media_type}"
        params = {
            "api_key": TMDB_API_KEY,
            "query": query,
            "language": "es-ES"
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("results", [])
        except Exception as e:
            logger.error(f"Error searching TMDB: {e}")
        
        return []
    
    async def get_tmdb_details(self, tmdb_id, media_type):
        """Obtiene detalles completos de TMDB"""
        await self.init_session()
        
        url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}"
        params = {
            "api_key": TMDB_API_KEY,
            "language": "es-ES",
            "append_to_response": "credits,videos,external_ids"
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
        except Exception as e:
            logger.error(f"Error getting TMDB details: {e}")
        
        return None
    
    async def search_omdb(self, title, year=None, media_type=None):
        """Busca en OMDB"""
        await self.init_session()
        
        params = {
            "apikey": OMDB_API_KEY,
            "t": title,
            "plot": "full"
        }
        
        if year:
            params["y"] = year
        if media_type:
            params["type"] = media_type
        
        try:
            async with self.session.get(OMDB_BASE_URL, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("Response") == "True":
                        return data
        except Exception as e:
            logger.error(f"Error searching OMDB: {e}")
        
        return None
    
    def find_best_match(self, query, results):
        """Encuentra la mejor coincidencia considerando errores tipográficos"""
        if not results:
            return None
        
        best_match = None
        best_score = 0
        
        for result in results:
            # Obtener título según el tipo de media
            if result.get("media_type") == "tv" or result.get("first_air_date"):
                title = result.get("name", "")
                original_title = result.get("original_name", "")
            else:
                title = result.get("title", "")
                original_title = result.get("original_title", "")
            
            # Calcular similitud con título y título original
            score1 = self.similarity(query, title)
            score2 = self.similarity(query, original_title)
            max_score = max(score1, score2)
            
            if max_score > best_score:
                best_score = max_score
                best_match = result
        
        # Solo devolver si la similitud es razonable (>0.6)
        return best_match if best_score > 0.6 else results[0]
    
    def format_basic_info(self, tmdb_data, omdb_data=None):
        """Formatea información básica"""
        if tmdb_data.get("media_type") == "tv" or tmdb_data.get("first_air_date"):
            # Es una serie
            title = tmdb_data.get("name", "N/A")
            original_title = tmdb_data.get("original_name", "")
            year = tmdb_data.get("first_air_date", "")[:4] if tmdb_data.get("first_air_date") else "N/A"
            runtime = f"{tmdb_data.get('episode_run_time', [45])[0]} min/episodio" if tmdb_data.get('episode_run_time') else "N/A"
            status = tmdb_data.get("status", "N/A")
            seasons = tmdb_data.get("number_of_seasons", "N/A")
            episodes = tmdb_data.get("number_of_episodes", "N/A")
            type_info = f"📺 Serie TV • {seasons} temporada(s) • {episodes} episodios"
        else:
            # Es una película
            title = tmdb_data.get("title", "N/A")
            original_title = tmdb_data.get("original_title", "")
            year = tmdb_data.get("release_date", "")[:4] if tmdb_data.get("release_date") else "N/A"
            runtime = f"{tmdb_data.get('runtime', 'N/A')} min" if tmdb_data.get('runtime') else "N/A"
            type_info = "🎬 Película"
        
        genres = ", ".join([g["name"] for g in tmdb_data.get("genres", [])])
        overview = tmdb_data.get("overview", "No disponible")
        
        text = f"🎭 **{title}** ({year})\n"
        if original_title and original_title != title:
            text += f"📝 *Título original: {original_title}*\n"
        text += f"{type_info}\n"
        text += f"⏱️ Duración: {runtime}\n"
        text += f"🎨 Géneros: {genres}\n\n"
        text += f"📖 **Sinopsis:**\n{overview}"
        
        return text
    
    def format_ratings(self, tmdb_data, omdb_data=None):
        """Formatea calificaciones"""
        text = "⭐ **CALIFICACIONES**\n\n"
        
        # TMDB
        if tmdb_data.get("vote_average"):
            tmdb_rating = tmdb_data["vote_average"]
            tmdb_votes = tmdb_data.get("vote_count", 0)
            text += f"🟢 **TMDB:** {tmdb_rating}/10 ({tmdb_votes:,} votos)\n"
        
        # OMDB ratings
        if omdb_data:
            if omdb_data.get("imdbRating") and omdb_data["imdbRating"] != "N/A":
                text += f"🟡 **IMDb:** {omdb_data['imdbRating']}/10\n"
            
            if omdb_data.get("Ratings"):
                for rating in omdb_data["Ratings"]:
                    source = rating["Source"]
                    value = rating["Value"]
                    if "Rotten Tomatoes" in source:
                        text += f"🍅 **Rotten Tomatoes:** {value}\n"
                    elif "Metacritic" in source:
                        text += f"🎯 **Metacritic:** {value}\n"
        
        return text if len(text) > len("⭐ **CALIFICACIONES**\n\n") else "⭐ No se encontraron calificaciones disponibles."
    
    def format_cast_crew(self, tmdb_data):
        """Formatea reparto y equipo"""
        text = "🎭 **REPARTO Y EQUIPO**\n\n"
        
        credits = tmdb_data.get("credits", {})
        
        # Director (solo para películas)
        if tmdb_data.get("media_type") != "tv" and not tmdb_data.get("first_air_date"):
            crew = credits.get("crew", [])
            directors = [person["name"] for person in crew if person["job"] == "Director"]
            if directors:
                text += f"🎬 **Director(es):** {', '.join(directors[:3])}\n\n"
        else:
            # Para series, mostrar creadores
            creators = tmdb_data.get("created_by", [])
            if creators:
                creator_names = [creator["name"] for creator in creators]
                text += f"👨‍💼 **Creador(es):** {', '.join(creator_names[:3])}\n\n"
        
        # Actores principales
        cast = credits.get("cast", [])
        if cast:
            text += "🎭 **Actores principales:**\n"
            for actor in cast[:8]:
                character = actor.get("character", "")
                char_text = f" como {character}" if character else ""
                text += f"• {actor['name']}{char_text}\n"
        
        return text if len(text) > len("🎭 **REPARTO Y EQUIPO**\n\n") else "🎭 No se encontró información del reparto."
    
    def format_where_to_watch(self, tmdb_data, omdb_data=None):
        """Formatea información de dónde ver"""
        text = "📺 **DÓNDE VER**\n\n"
        
        # Información básica de disponibilidad
        if omdb_data and omdb_data.get("Type"):
            media_type = "película" if omdb_data["Type"] == "movie" else "serie"
            text += f"🎬 Busca esta {media_type} en:\n"
        
        text += "🔍 **Plataformas sugeridas:**\n"
        text += "• Netflix\n• Amazon Prime Video\n• Disney+\n• HBO Max\n• Apple TV+\n• Paramount+\n"
        text += "\n💡 **Tip:** Usa JustWatch.com para verificar disponibilidad en tu región"
        
        # Si hay información del año, agregar contexto
        if tmdb_data.get("release_date") or tmdb_data.get("first_air_date"):
            date_field = "release_date" if tmdb_data.get("release_date") else "first_air_date"
            year = tmdb_data[date_field][:4]
            current_year = datetime.now().year
            
            if int(year) >= current_year - 2:
                text += f"\n🆕 **Nuevo:** Lanzado en {year}, probablemente disponible en streaming"
        
        return text

# Instancia global del bot
movie_bot = MovieBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando de inicio con mensaje creativo"""
    welcome_message = """
🎬✨ ¡Bienvenida Mika, Makaveli te Saluda hizo este bot para ti para que no lo extrañes jaja(prueba1) **@Mikalabaza_ayuda_bot**! ✨🎭

(⚙ MANTENIMIENTO puedes beber mate mientras lo arrelgamos jaja)

🎯 **¿Qué puedo hacer por ti?** (aparte de todo bb)
Simplemente escribe el nombre de cualquier película o serie y te daré toda la información que necesitas:

🔍 **Búsqueda inteligente** - Tolero errores tipográficos y modismos argentinos Che!
📊 **Información completa** - IMDb, TMDB, Metacritic y más
🎭 **Reparto y equipo** - Actores, directores, creadores
⭐ **Calificaciones** - De múltiples fuentes
📺 **Dónde ver** - Plataformas de streaming

💡 **Ejemplos de uso:**
• ""
• "Good Fellas"
• "breaking bad"
• "el padrno" (sí, con errores)
• "inception"
• "game of trones"

🚀 **¡Pruébame ahora!** Escribe el nombre de tu película o serie favorita.

---
💻 Powered by Makaveli para Mikaela con cariño... 🫶🏼
    """
    
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando de ayuda"""
    help_text = """
🆘 **AYUDA - CINEGRAM INFO BOT**

🎯 **Cómo usar el bot:**
1. Simplemente escribe el nombre de una película o serie
2. No necesitas comandos especiales
3. Puedo entender títulos con errores tipográficos
4. Funciono tanto en chats privados como en grupos

📋 **Comandos disponibles:**
• `/start` - Mensaje de bienvenida
• `/help` - Esta ayuda
• `/about` - Información sobre el bot

🔍 **Ejemplos de búsqueda:**
• "Avengers Endgame"
• "la casa de papel"
• "stranger things"
• "el señor de los anillos"

🤖 **En grupos:**
• Respondo automáticamente a títulos de películas/series
• También puedes mencionarme: @cinegraminfobot título

❓ **¿Problemas?** Asegúrate de escribir el título lo más completo posible.
    """
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Información sobre el bot"""
    about_text = """
ℹ️ **SOBRE CINEGRAM INFO BOT**

🎬 **Versión:** 1.0
👨‍💻 **Desarrollado con:** Python + Telegram Bot API

📊 **Fuentes de datos:**
• 🎭 The Movie Database (TMDB)
• 🌟 Open Movie Database (OMDb)
• 📺 JustWatch (para streaming)
• ⭐ IMDb, Rotten Tomatoes, Metacritic

🚀 **Características:**
• Búsqueda tolerante a errores
• Información en español e inglés
• Interfaz con botones interactivos  
• Soporte para películas y series
• Funciona en grupos y chats privados

🔄 **Última actualización:** Junio 2025

💝 **¿Te gusta el bot?** ¡Compártelo con tus amigos cinéfilos!
    """
    
    await update.message.reply_text(about_text, parse_mode='Markdown')

def create_info_keyboard(media_data):
    """Crea teclado con botones de información"""
    # Determinar media_type correctamente
    if media_data.get("media_type") == "tv" or media_data.get("first_air_date"):
        media_type = "tv"
    else:
        media_type = "movie"
    
    keyboard = [
        [
            InlineKeyboardButton("📽️ Info Básica", callback_data=f"basic|{media_data['id']}|{media_type}"),
            InlineKeyboardButton("⭐ Calificaciones", callback_data=f"ratings|{media_data['id']}|{media_type}")
        ],
        [
            InlineKeyboardButton("🎭 Reparto", callback_data=f"cast|{media_data['id']}|{media_type}"),
            InlineKeyboardButton("📺 Dónde Ver", callback_data=f"watch|{media_data['id']}|{media_type}")
        ],
        [
            InlineKeyboardButton("🔄 Nueva Búsqueda", callback_data="new_search")
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja mensajes que podrían ser títulos de películas/series"""
    message_text = update.message.text.strip()
    
    # Ignorar comandos
    if message_text.startswith('/'):
        return
    
    # Filtro básico para detectar posibles títulos
    if len(message_text) < 2 or len(message_text) > 100:
        return
    
    # En grupos, solo responder si nos mencionan o si parece un título claro
    if update.effective_chat.type in ['group', 'supergroup']:
        bot_username = context.bot.username
        if f"@{bot_username}" not in message_text:
            # Heurística simple: debe tener letras y posiblemente números/espacios
            if not re.match(r'^[a-zA-ZñÑáéíóúÁÉÍÓÚ0-9\s\-:.,\'\"]+$', message_text):
                return
            # Muy corto o muy común, probablemente no es un título
            if len(message_text) < 3 or message_text.lower() in ['si', 'no', 'ok', 'hola', 'que', 'como']:
                return
        else:
            # Si nos mencionaron, extraer el título
            message_text = message_text.replace(f"@{bot_username}", "").strip()
    
    # Mostrar que está escribiendo
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        # Buscar en TMDB
        results = await movie_bot.search_tmdb(message_text)
        
        if not results:
            await update.message.reply_text(
                f"🔍 No encontré resultados para '{message_text}'\n\n"
                "💡 **Consejos:**\n"
                "• Verifica la ortografía\n"
                "• Prueba con el título en inglés\n"
                "• Usa títulos más específicos"
            )
            return
        
        # Encontrar la mejor coincidencia
        best_match = movie_bot.find_best_match(message_text, results)
        
        if not best_match:
            await update.message.reply_text("❌ No pude encontrar una coincidencia adecuada.")
            return
        
        # Determinar tipo de media
        media_type = "tv" if best_match.get("media_type") == "tv" or best_match.get("first_air_date") else "movie"
        
        # Obtener poster si está disponible
        poster_path = best_match.get("poster_path")
        poster_url = f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None
        
        # Crear mensaje inicial con título y poster
        if media_type == "tv":
            title = best_match.get("name", "Título desconocido")
            year = best_match.get("first_air_date", "")[:4] if best_match.get("first_air_date") else ""
        else:
            title = best_match.get("title", "Título desconocido")
            year = best_match.get("release_date", "")[:4] if best_match.get("release_date") else ""
        
        initial_message = f"🎬 **{title}**"
        if year:
            initial_message += f" ({year})"
        initial_message += f"\n\n📊 Selecciona qué información quieres ver:"
        
        keyboard = create_info_keyboard(best_match)
        
        if poster_url:
            try:
                await update.message.reply_photo(
                    photo=poster_url,
                    caption=initial_message,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
            except:
                # Si falla la imagen, enviar solo texto
                await update.message.reply_text(
                    initial_message,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                initial_message,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text(
            "❌ Ocurrió un error al procesar tu solicitud. Por favor, inténtalo de nuevo."
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los callbacks de los botones - VERSIÓN CORREGIDA"""
    query = update.callback_query
    await query.answer()
    
    # Log para debug
    logger.info(f"Callback received: {query.data}")
    
    if query.data == "new_search":
        try:
            # Intentar editar el mensaje, si falla enviar uno nuevo
            if query.message.photo:
                # Si es una foto, enviar mensaje nuevo
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="🔍 **Nueva búsqueda**\n\nEscribe el nombre de otra película o serie que quieras buscar.",
                    parse_mode='Markdown'
                )
            else:
                # Si es texto, editar
                await query.edit_message_text(
                    "🔍 **Nueva búsqueda**\n\nEscribe el nombre de otra película o serie que quieras buscar.",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Error in new_search: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="🔍 **Nueva búsqueda**\n\nEscribe el nombre de otra película o serie que quieras buscar.",
                parse_mode='Markdown'
            )
        return
    
    # Parsear callback data - CAMBIADO DE _ A |
    try:
        parts = query.data.split('|')
        if len(parts) != 3:
            logger.error(f"Invalid callback data format: {query.data}")
            await query.edit_message_text("❌ Error en los datos del botón.")
            return
            
        action, tmdb_id, media_type = parts
        tmdb_id = int(tmdb_id)
        
        logger.info(f"Parsed: action={action}, id={tmdb_id}, type={media_type}")
        
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing callback data: {e}")
        await query.edit_message_text("❌ Error en los datos del botón.")
        return
    
    # Mostrar indicador de carga
    await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
    
    try:
        # Obtener detalles completos de TMDB
        logger.info(f"Fetching TMDB details for {media_type} ID {tmdb_id}")
        tmdb_details = await movie_bot.get_tmdb_details(tmdb_id, media_type)
        
        if not tmdb_details:
            logger.error(f"No TMDB details found for {media_type} ID {tmdb_id}")
            await query.edit_message_text("❌ No se pudieron obtener los detalles.")
            return
        
        # Obtener datos de OMDB para calificaciones adicionales
        omdb_data = None
        if action == "ratings":
            title = tmdb_details.get("title") or tmdb_details.get("name")
            if title:
                year = None
                if tmdb_details.get("release_date"):
                    year = tmdb_details["release_date"][:4]
                elif tmdb_details.get("first_air_date"):
                    year = tmdb_details["first_air_date"][:4]
                
                omdb_data = await movie_bot.search_omdb(title, year, "movie" if media_type == "movie" else "series")
        
        # Generar contenido según la acción
        if action == "basic":
            content = movie_bot.format_basic_info(tmdb_details, omdb_data)
        elif action == "ratings":
            content = movie_bot.format_ratings(tmdb_details, omdb_data)
        elif action == "cast":
            content = movie_bot.format_cast_crew(tmdb_details)
        elif action == "watch":
            content = movie_bot.format_where_to_watch(tmdb_details, omdb_data)
        else:
            content = "❌ Acción no reconocida."
            logger.error(f"Unknown action: {action}")
        
        # Crear nuevo keyboard
        keyboard = create_info_keyboard({
            'id': tmdb_id, 
            'media_type': media_type,
            'first_air_date': tmdb_details.get('first_air_date')
        })
        
        # Intentar editar mensaje
        try:
            if query.message.photo:
                # Si el mensaje original tiene foto, editar solo el caption
                await query.edit_message_caption(
                    caption=content,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
            else:
                # Si es solo texto, editar el texto
                await query.edit_message_text(
                    content,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
        except Exception as edit_error:
            logger.error(f"Error editing message: {edit_error}")
            # Si no se puede editar, enviar mensaje nuevo
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=content,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Error in button callback: {e}")
        try:
            await query.edit_message_text(
                "❌ Ocurrió un error al obtener la información. Inténtalo de nuevo.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Reintentar", callback_data=query.data)
                ]])
            )
        except:
            # Si no se puede editar, enviar mensaje nuevo
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Ocurrió un error al obtener la información. Inténtalo de nuevo."
            )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja errores globales"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Función principal"""
    print("🎬 Iniciando Cinegram Info Bot...")
    
    # Verificar tokens
    if not TELEGRAM_TOKEN or not TMDB_API_KEY or not OMDB_API_KEY:
        print("❌ ERROR: Faltan tokens de API!")
        return
    
    # Crear aplicación
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Agregar handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    print("✅ Bot configurado correctamente")
    print("🚀 Iniciando polling...")
    print("📱 Busca tu bot en Telegram y escribe /start")
    print("🛑 Presiona Ctrl+C para detener")
    
    # Iniciar bot
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Bot detenido por el usuario")
    finally:
        # Limpiar recursos
        asyncio.run(movie_bot.close_session())

if __name__ == '__main__':
    main()
