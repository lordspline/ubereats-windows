import asyncio
import base64
from enum import Enum
import os
import win32gui
import win32con
import pyautogui
from pathlib import Path
from uuid import uuid4
from typing import Literal, TypedDict
from anthropic.types.beta import BetaToolComputerUse20241022Param
from .base import BaseAnthropicTool, ToolError, ToolResult
from PIL import ImageGrab, Image, ImageDraw
import logging

OUTPUT_DIR = "C:\\temp\\outputs"

TYPING_DELAY_MS = 12
TYPING_GROUP_SIZE = 50

Action = Literal[
    "key",
    "type",
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "screenshot",
    "cursor_position",
]


class Resolution(TypedDict):
    width: int
    height: int


# sizes above XGA/WXGA are not recommended (see README.md)
# scale down to one of these targets if ComputerTool._scaling_enabled is set
MAX_SCALING_TARGETS: dict[str, Resolution] = {
    "XGA": Resolution(width=1024, height=768),  # 4:3
    "WXGA": Resolution(width=1280, height=800),  # 16:10
    "FWXGA": Resolution(width=1366, height=768),  # ~16:9
}


class ScalingSource(Enum):
    COMPUTER = "computer"
    API = "api"


class ComputerToolOptions(TypedDict):
    display_height_px: int
    display_width_px: int
    display_number: int | None


def chunks(s: str, chunk_size: int) -> list[str]:
    return [s[i : i + chunk_size] for i in range(0, len(s), chunk_size)]


class ComputerTool(BaseAnthropicTool):
    """Windows version of ComputerTool"""
    
    name: Literal["computer"] = "computer"
    api_type: Literal["computer_20241022"] = "computer_20241022"
    width: int
    height: int
    display_num: int | None

    _screenshot_delay = 2.0
    _scaling_enabled = True

    @property
    def options(self) -> ComputerToolOptions:
        width, height = self.scale_coordinates(
            ScalingSource.COMPUTER, self.width, self.height
        )
        return {
            "display_width_px": width,
            "display_height_px": height,
            "display_number": self.display_num,
        }

    def to_params(self) -> BetaToolComputerUse20241022Param:
        return {"name": self.name, "type": self.api_type, **self.options}

    def __init__(self):
        super().__init__()

        self.width = int(os.getenv("WIDTH") or 0)
        self.height = int(os.getenv("HEIGHT") or 0)
        assert self.width and self.height, "WIDTH, HEIGHT must be set"
        if (display_num := os.getenv("DISPLAY_NUM")) is not None:
            self.display_num = int(display_num)
            self._display_prefix = f"DISPLAY=:{self.display_num} "
        else:
            self.display_num = None
            self._display_prefix = ""

        self.xdotool = f"{self._display_prefix}xdotool"

    async def __call__(self, *, action: Action, text: str | None = None, coordinate: tuple[int, int] | None = None, **kwargs):
        if action in ("mouse_move", "left_click_drag"):
            if coordinate is None:
                raise ToolError(f"coordinate is required for {action}")
            x, y = self.scale_coordinates(ScalingSource.API, coordinate[0], coordinate[1])
            
            if action == "mouse_move":
                pyautogui.moveTo(x, y)
                await asyncio.sleep(self._screenshot_delay)
                screenshot_base64 = (await self.screenshot()).base64_image
                return ToolResult(base64_image=screenshot_base64)
            elif action == "left_click_drag":
                pyautogui.mouseDown()
                pyautogui.moveTo(x, y)
                pyautogui.mouseUp()
                await asyncio.sleep(self._screenshot_delay)
                screenshot_base64 = (await self.screenshot()).base64_image
                return ToolResult(base64_image=screenshot_base64)

        if action in ("key", "type"):
            if text is None:
                raise ToolError(f"text is required for {action}")
                
            if action == "key":
                pyautogui.press(text)
                await asyncio.sleep(self._screenshot_delay)
                screenshot_base64 = (await self.screenshot()).base64_image
                return ToolResult(base64_image=screenshot_base64)
            elif action == "type":
                pyautogui.write(text, interval=TYPING_DELAY_MS/1000)
                await asyncio.sleep(self._screenshot_delay)
                screenshot_base64 = (await self.screenshot()).base64_image
                return ToolResult(base64_image=screenshot_base64)

        if action in ("left_click", "right_click", "double_click", "middle_click", "screenshot", "cursor_position"):
            if action == "screenshot":
                return await self.screenshot()
            elif action == "cursor_position":
                x, y = pyautogui.position()
                x, y = self.scale_coordinates(ScalingSource.COMPUTER, x, y)
                return ToolResult(output=f"X={x},Y={y}")
            else:
                click_map = {
                    "left_click": pyautogui.click,
                    "right_click": pyautogui.rightClick,
                    "middle_click": pyautogui.middleClick,
                    "double_click": lambda: pyautogui.click(clicks=2)
                }
                click_map[action]()
                await asyncio.sleep(self._screenshot_delay)
                screenshot_base64 = (await self.screenshot()).base64_image
                return ToolResult(base64_image=screenshot_base64)

        raise ToolError(f"Invalid action: {action}")

    async def screenshot(self):
        """Take a screenshot using PIL's ImageGrab and draw a cursor indicator"""
        from PIL import Image, ImageDraw
        import win32gui
        
        output_dir = Path(OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"screenshot_{uuid4().hex}.png"
        
        # Take the screenshot
        screenshot = ImageGrab.grab()
        
        try:
            # Get cursor position and draw indicator
            cursor_pos = win32gui.GetCursorPos()
            draw = ImageDraw.Draw(screenshot)
            
            # Draw cursor arrow
            x, y = cursor_pos
            cursor_points = [
                (x, y),  # Tip of cursor
                (x + 16, y + 16),  # Bottom right
                (x, y + 11),  # Bottom middle indent
                (x + 11, y),  # Middle right indent
                (x, y)  # Back to tip
            ]
            
            # Draw white cursor with black border
            draw.polygon(cursor_points, fill='white', outline='black')
            
        except Exception:
            # If cursor drawing fails, continue with basic screenshot
            pass
        
        # Handle scaling if enabled
        if self._scaling_enabled:
            x, y = self.scale_coordinates(ScalingSource.COMPUTER, self.width, self.height)
            screenshot = screenshot.resize((x, y))
        
        # Save and cleanup
        screenshot.save(str(path))
        
        if path.exists():
            try:
                base64_image = base64.b64encode(path.read_bytes()).decode()
                path.unlink()  # Delete the temporary file
                return ToolResult(base64_image=base64_image)
            except Exception:
                if path.exists():
                    path.unlink()  # Ensure cleanup even if encoding fails
                raise ToolError("Failed to encode screenshot")
        
        raise ToolError("Failed to take screenshot")

    def scale_coordinates(self, source: ScalingSource, x: int, y: int):
        """Scale coordinates to a target maximum resolution."""
        if not self._scaling_enabled:
            return x, y
        ratio = self.width / self.height
        target_dimension = None
        for dimension in MAX_SCALING_TARGETS.values():
            # allow some error in the aspect ratio - not ratios are exactly 16:9
            if abs(dimension["width"] / dimension["height"] - ratio) < 0.02:
                if dimension["width"] < self.width:
                    target_dimension = dimension
                break
        if target_dimension is None:
            return x, y
        # should be less than 1
        x_scaling_factor = target_dimension["width"] / self.width
        y_scaling_factor = target_dimension["height"] / self.height
        if source == ScalingSource.API:
            if x > self.width or y > self.height:
                raise ToolError(f"Coordinates {x}, {y} are out of bounds")
            # scale up
            return round(x / x_scaling_factor), round(y / y_scaling_factor)
        # scale down
        return round(x * x_scaling_factor), round(y * y_scaling_factor)
