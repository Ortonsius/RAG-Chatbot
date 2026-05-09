from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile
import os

router = Router()

class SystemPromptForm(StatesGroup):
    waiting_for_prompt = State()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 <b>AutoAI Assistant</b>\n\n"
        "I'm an AI agent with memory and tool-use capabilities. You can ask me anything, upload documents for me to learn from, and even let me execute Linux commands on your behalf.\n\n"
        "<b>Commands:</b>\n"
        "/reset - Reset the current conversation\n"
        "/system_prompt - Set a custom system prompt\n"
        "/memory_reset - Clear all knowledge from the vector database\n"
        "/memory_del - Delete a specific document from memory (by filename)\n"
        "/cancel - Cancel the current operation (e.g., LLM generation)"
    )

@router.message(Command("reset"))
async def cmd_reset(message: types.Message, state: FSMContext):
    await state.update_data(history=[])
    await message.answer("✅ Conversation history has been reset.")

@router.message(Command("system_prompt"))
async def cmd_system_prompt(message: types.Message, state: FSMContext):
    await state.set_state(SystemPromptForm.waiting_for_prompt)
    await message.answer(
        "📝 <b>Set Custom System Prompt</b>\n\n"
        "Please send me the new system prompt. This will guide my behavior for all future interactions until reset.\n"
        "Send /cancel to abort."
    )

@router.message(SystemPromptForm.waiting_for_prompt)
async def process_system_prompt(message: types.Message, state: FSMContext):
    if message.text == "/cancel":
        await state.set_state(None)
        await message.answer("❌ Operation cancelled.")
        return
    
    await state.clear()
    await state.update_data(system_prompt=message.text)
    await message.answer(f"✅ System prompt updated to:\n\n<code>{message.text}</code>")

@router.message(Command("memory_reset"))
async def cmd_memory_reset(message: types.Message):
    from services.memory import MemoryService
    memory = MemoryService()
    try:
        memory.delete_collection()
        memory.create_collection()
        await message.answer("🧹 <b>Memory Reset Complete</b>\n\nAll knowledge has been cleared from the vector database.")
    except Exception as e:
        await message.answer(f"❌ Error resetting memory: {e}")

@router.message(Command("memory_del"))
async def cmd_memory_del(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Usage: /memory_del [filename]\nExample: /memory_del report.pdf")
        return
    
    filename = parts[1].strip()
    from services.memory import MemoryService
    memory = MemoryService()
    try:
        count = await memory.delete_by_filename(filename)
        if count > 0:
            await message.answer(f"✅ Deleted {count} chunks associated with '{filename}'.")
        else:
            await message.answer(f"ℹ️ No memory entries found for '{filename}'.")
    except Exception as e:
        await message.answer(f"❌ Error deleting memory: {e}")

@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    data = await state.get_data()
    task: asyncio.Task = data.get("current_task")
    if task and not task.done():
        task.cancel()
        await message.answer("🛑 Operation cancelled.")
    else:
        await message.answer("ℹ️ No active operation to cancel.")
    await state.update_data(current_task=None)