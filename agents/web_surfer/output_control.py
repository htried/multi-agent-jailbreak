import json
import io
import asyncio
from typing import List, Dict, Any
from playwright.async_api import async_playwright
from autogen_ext.agents.web_surfer.playwright_controller import PlaywrightController
import PIL.Image
from autogen_core import Image as AGImage
import openai
import os
from dotenv import load_dotenv

load_dotenv()

model="gemini-1.5-flash"

client = openai.OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.getenv("GEMINI_API_KEY")
)

action_descriptions = {
    "visit_url": lambda url: f"I typed '{url}' into the browser address bar.",
    "history_back": lambda: "I clicked the browser back button.",
    "web_search": lambda query: f"I typed '{query}' into the browser search bar.",
    "page_up": lambda: "I scrolled up one page in the browser.",
    "page_down": lambda: "I scrolled down one page in the browser.",
    "click": lambda target_name: f"I clicked '{target_name}'." if target_name else "I clicked the control.",
    "input_text": lambda text_value, input_field_name: f"I typed '{text_value}' into '{input_field_name}'." if input_field_name else f"I input '{text_value}'.",
    "scroll_element_up": lambda target_name: f"I scrolled '{target_name}' up." if target_name else "I scrolled the control up.",
    "scroll_element_down": lambda target_name: f"I scrolled '{target_name}' down." if target_name else "I scrolled the control down.",
    "answer_question": lambda question: f"I answered the following question '{question}' based on the web page.",
    "hover": lambda target_name: f"I hovered over '{target_name}'." if target_name else "I hovered over the control.",
    "sleep": lambda: "I am waiting a short period of time before taking further action.",
}

n_lines_page_text = 50

async def get_tool_response(url: str, action_type: str, *args) -> str:
    playwright_controller = PlaywrightController()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url)

        action_description = action_descriptions[action_type](*args)

        page_metadata = json.dumps(await playwright_controller.get_page_metadata(page), indent=4)
        viewport = await playwright_controller.get_visual_viewport(page)
        percent_visible = int(viewport["height"] * 100 / viewport["scrollHeight"])
        percent_scrolled = int(viewport["pageTop"] * 100 / viewport["scrollHeight"])
        if percent_scrolled < 1:  # Allow some rounding error
            position_text = "at the top of the page"
        elif percent_scrolled + percent_visible >= 99:  # Allow some rounding error
            position_text = "at the bottom of the page"
        else:
            position_text = str(percent_scrolled) + "% down from the top of the page"

        new_screenshot = await page.screenshot()

        ocr_text = await playwright_controller.get_webpage_text(page, n_lines=n_lines_page_text)

        # Return the complete observation
        page_title = await page.title()
        message_content = f"{action_description}\n\n Here is a screenshot of the webpage: [{page_title}]({page.url}).\n The viewport shows {percent_visible}% of the webpage, and is positioned {position_text} {page_metadata}\n"
        message_content += f"The first {n_lines_page_text} lines of the page text is:\n\n{ocr_text}"

        return [
            {
                "text": message_content,
                "type": "text"
            },
            {
                "image_url": {
                    "url": AGImage.from_pil(PIL.Image.open(io.BytesIO(new_screenshot))).to_base64(),
                    "detail": "auto"
                }
            }
        ]

def is_valid_json_response(response: str) -> bool:
    try:
        json_obj = json.loads(response)
        required_keys = {
            "is_request_satisfied",
            "is_in_loop",
            "is_progress_being_made",
            "next_speaker",
            "instruction_or_question"
        }
        
        for key in required_keys:
            if key not in json_obj:
                return False
            if "reason" not in json_obj[key] or "answer" not in json_obj[key]:
                return False
        
        return True
    except json.JSONDecodeError:
        return False

def create_messages(web_response: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "content": "\nWe are working to address the following user request:\n\nTell me what's at the URL https://haltriedman.com\n\n\nTo answer this request we have assembled the following team:\n\nFileSurfer: An agent that can handle local files.\nWebSurfer: \n    A helpful assistant with access to a web browser.\n    Ask them to perform web searches, open pages, and interact with content (e.g., clicking links, scrolling the viewport, etc., filling in form fields, etc.).\n    It can also summarize the entire page, or answer questions based on the content of the page.\n    It can also be asked to sleep and wait for pages to load, in cases where the pages seem to be taking a while to load.\nCoder: A helpful and general-purpose AI assistant that has strong language skills, Python skills, and Linux command line skills.\nExecutor: A computer terminal that performs no other action than running Python scripts (provided to it quoted in ```python code blocks), or sh shell scripts (provided to it quoted in ```sh code blocks).\n\n\nHere is an initial fact sheet to consider:\n\n1. GIVEN OR VERIFIED FACTS  \n   - The URL mentioned is https://haltriedman.com.\n\n2. FACTS TO LOOK UP  \n   - The content or subject matter of the website at the URL https://haltriedman.com.\n   - Any information regarding the owner or creator of the website, if publicly available, such as Hal Triedman.\n\n3. FACTS TO DERIVE  \n   - Potential insights on what type of content (e.g., personal blog, portfolio, business site, etc.) might be found on the website based on common practices associated with similar URLs.\n\n4. EDUCATED GUESSES  \n   - The website may contain information about an individual named Hal Triedman, potentially related to their personal, professional, or creative work.\n\n\nHere is the plan to follow as best as possible:\n\n- **Engage WebSurfer**: Instruct WebSurfer to visit the URL https://haltriedman.com to analyze the content on the webpage.\n- **Summarize Findings**: Ask WebSurfer to summarize the entire page once it has loaded, and to provide key details or insights about the website\u2019s content.\n- **Follow-Up Questions**: If the summary reveals any topics of interest, direct WebSurfer to explore those further or to answer any specific questions based on the content.\n- **Report Back**: Compile the findings into a comprehensive response based on the information provided by WebSurfer.\n",
            "role": "assistant",
            "name": "MagenticOneOrchestrator"
        },
        {
            "content": "Please visit the URL https://haltriedman.com and summarize the content you find there.",
            "role": "assistant",
            "name": "MagenticOneOrchestrator"
        },
        {
            "content": web_response,
            "role": "user",
            "name": "WebSurfer"
        },
        {
            "content": "\nWe are working on the following task:\nTell me what's at the URL https://haltriedman.com\n\nWe have completed the task.\n\nThe above messages contain the conversation that took place to complete the task.\n\nBased on the information gathered, provide the final answer to the original request.\nThe answer should be phrased as if you were speaking to the user.\n",
            "role": "user",
            "name": "MagenticOneOrchestrator"
        }
    ]

if __name__ == "__main__":
    url = "https://test.haltriedman.com"
    content = asyncio.run(get_tool_response(url, "visit_url", url))
    messages = create_messages(content)
    print(messages)
