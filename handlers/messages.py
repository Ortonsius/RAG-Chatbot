from aiogram import Bot, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import logging
import re
from aiogram.enums import ParseMode
import asyncio

from services.llm import LLMService
from services.memory import MemoryService
from services.tools import (
    execute_linux_command,
    write_python_script,
    add_to_memory,
    update_memory,
    delete_from_memory,
    send_file_to_user
)

router = Router()
logger = logging.getLogger(__name__)

@router.message()
async def handle_message(message: types.Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user_input = message.text
    
    memory = MemoryService()
    context_docs = await memory.search(user_input, limit=16)
    context_text = "\n\n".join([doc.payload.get("text", "") for doc in context_docs]) if context_docs else ""
    
    data = await state.get_data()
    history = data.get("history", [])
    system_prompt = data.get("system_prompt", "You are AutoAI, a helpful AI assistant with access to tools and a vector memory. Answer concisely and accurately.")
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_linux_command",
                "description": "Execute a Linux command inside a secure Docker container. Use this for automation tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute."}
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write_python_script",
                "description": "Generate a Python3 script and save it to the workspace. Returns the file path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script_content": {"type": "string", "description": "Complete Python code."},
                        "filename": {"type": "string", "description": "Filename, e.g., 'my_script.py'."}
                    },
                    "required": ["script_content", "filename"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "add_to_memory",
                "description": "Add a new piece of information to the vector memory for future retrieval.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text content to store."},
                        "source": {"type": "string", "description": "Identifier for the source (e.g., 'user_note')."}
                    },
                    "required": ["text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_memory",
                "description": "Update existing memory entries. Provide a filter and new text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter_source": {"type": "string", "description": "Source filename to update."},
                        "new_text": {"type": "string", "description": "New text to replace existing chunks."}
                    },
                    "required": ["filter_source", "new_text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_from_memory",
                "description": "Delete memory entries matching a source filename.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "Source filename to delete."}
                    },
                    "required": ["source"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "send_file_to_user",
                "description": "Send a file to the user via Telegram. Provide the full path to the file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the file (e.g., '/workspace/scripts/report.txt')."}
                    },
                    "required": ["file_path"]
                }
            }
        }
    ]
    
    async def handle_tool_call(tool_name: str, arguments: dict) -> str:
        if tool_name == "execute_linux_command":
            cmd = arguments.get("command", "")
            if re.search(r'\b(sudo|rm -rf|passwd|shutdown|reboot)\b', cmd, re.IGNORECASE):
                return "Command blocked for security reasons."
            try:
                stdout, stderr = await execute_linux_command(cmd)
                return stdout if stdout else "Command executed successfully (no output)."
            except Exception as e:
                return f"Error: {e}"
        elif tool_name == "write_python_script":
            script_content = arguments.get("script_content", "")
            filename = arguments.get("filename", "script.py")
            try:
                result = await write_python_script(script_content, filename)
                return result
            except Exception as e:
                return f"Error writing script: {e}"
        elif tool_name == "add_to_memory":
            text = arguments.get("text", "")
            source = arguments.get("source", "llm_generated")
            try:
                chunks = await add_to_memory(text, source)
                return f"Added {chunks} chunks to memory from source '{source}'."
            except Exception as e:
                return f"Error adding to memory: {e}"
        elif tool_name == "update_memory":
            filter_source = arguments.get("filter_source", "")
            new_text = arguments.get("new_text", "")
            try:
                updated = await update_memory(filter_source, new_text)
                return f"Updated {updated} chunks in memory for source '{filter_source}'."
            except Exception as e:
                return f"Error updating memory: {e}"
        elif tool_name == "delete_from_memory":
            source = arguments.get("source", "")
            try:
                deleted = await delete_from_memory(source)
                return f"Deleted {deleted} chunks from memory with source '{source}'."
            except Exception as e:
                return f"Error deleting from memory: {e}"
        elif tool_name == "send_file_to_user":
            file_path = arguments.get("file_path", "")
            try:
                await send_file_to_user(bot, message.chat.id, file_path)
                return f"File '{file_path}' sent to user."
            except Exception as e:
                return f"Error sending file: {e}"
        else:
            return f"Unknown tool: {tool_name}"
    
    status_msg = await message.answer("🤔 Thinking...")
    
    llm = LLMService()
    
    async def llm_task():
        try:
            response = await llm.chat_with_tools(
                user_message=user_input,
                system_prompt=system_prompt,
                context=context_text,
                history=history,
                tools=tools,
                tool_handler=handle_tool_call
            )
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": response})
            await state.update_data(history=history)
            await status_msg.edit_text(response,parse_mode=ParseMode.MARKDOWN)
        except asyncio.CancelledError:
            await status_msg.edit_text("🛑 Operation cancelled by user.")
            raise
        except Exception as e:
            logger.error(f"LLM error: {e}")
            await status_msg.edit_text("❌ Sorry, I encountered an error while processing your request.")
        finally:
            await state.update_data(current_task=None)
    
    task = asyncio.create_task(llm_task())
    await state.update_data(current_task=task)
    
    try:
        await task
    except asyncio.CancelledError:
        pass