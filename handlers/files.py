import os
import tempfile
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
import logging

from utils.file_parser import extract_text_from_file
from services.memory import MemoryService

router = Router()
logger = logging.getLogger(__name__)

@router.message(F.document)
async def handle_document(message: types.Message, state: FSMContext):
    document = message.document
    file_name = document.file_name
    file_size = document.file_size

    if file_size > 20 * 1024 * 1024:
        await message.answer("❌ File is too large. Please upload a file smaller than 20MB.")
        return

    status_msg = await message.answer(f"📄 Processing '{file_name}'...")

    file = await message.bot.get_file(document.file_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as tmp_file:
        await message.bot.download_file(file.file_path, tmp_file.name)
        tmp_path = tmp_file.name

    try:
        text_content = extract_text_from_file(tmp_path, file_name)
        if not text_content:
            await status_msg.edit_text(f"⚠️ No text content could be extracted from '{file_name}'.")
            return

        memory = MemoryService()
        num_chunks = await memory.add_document(text_content, {"source": file_name})
        
        await status_msg.edit_text(
            f"✅ <b>Document Processed Successfully!</b>\n\n"
            f"📁 File: <code>{file_name}</code>\n"
            f"📊 Chunks added: {num_chunks}\n"
            f"💾 Total memory size: {await memory.get_collection_size()}"
        )
        logger.info(f"Added document '{file_name}' to memory with {num_chunks} chunks.")

    except Exception as e:
        logger.error(f"Error processing file {file_name}: {e}")
        await status_msg.edit_text(f"❌ An error occurred while processing '{file_name}': {e}")
    finally:
        os.unlink(tmp_path)