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
import win32ui
import win32api
from ctypes import windll
import time

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
        
        # Disable PyAutoGUI failsafe
        pyautogui.FAILSAFE = False
        
        # Get screen size from pyautogui
        self.width, self.height = pyautogui.size()
        
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
            print(f"Scaling coordinates: {x}, {y}")
            
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
        """Take a screenshot using multiple fallback methods"""
        output_dir = Path(OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"screenshot_{uuid4().hex}.png"

        try:
            # Try multiple screenshot methods
            screenshot = None
            error_messages = []

            # Method 1: Try PIL ImageGrab
            try:
                screenshot = ImageGrab.grab()
            except Exception as e:
                error_messages.append(f"PIL ImageGrab failed: {str(e)}")

            # Method 2: Try Win32 API if PIL failed
            if screenshot is None:
                try:
                    screenshot = self._win32_screenshot()
                except Exception as e:
                    error_messages.append(f"Win32 screenshot failed: {str(e)}")

            # If both methods failed, raise error
            if screenshot is None:
                raise ToolError(f"All screenshot methods failed: {'; '.join(error_messages)}")

            # Draw cursor (optional - won't fail if this doesn't work)
            try:
                cursor_pos = win32gui.GetCursorPos()
                draw = ImageDraw.Draw(screenshot)
                
                x, y = cursor_pos
                
                # Draw crosshair
                size = 20
                draw.line((x - size, y, x + size, y), fill='red', width=2)
                draw.line((x, y - size, x, y + size), fill='red', width=2)
                
                # Draw simple triangle cursor
                points = [(x, y), (x + 16, y + 24), (x + 24, y + 16)]
                draw.polygon(points, fill='white', outline='black')
            except Exception:
                # Continue without cursor if drawing fails
                pass

            # Handle scaling if enabled
            if self._scaling_enabled:
                try:
                    x, y = self.scale_coordinates(ScalingSource.COMPUTER, self.width, self.height)
                    screenshot = screenshot.resize((x, y))
                except Exception as e:
                    logging.warning(f"Scaling failed: {str(e)}")

            # Save and encode
            try:
                screenshot.save(str(path))
                if path.exists():
                    base64_image = base64.b64encode(path.read_bytes()).decode()
                    path.unlink()
                    return ToolResult(base64_image=base64_image)
            except Exception as e:
                if path.exists():
                    path.unlink()
                raise ToolError(f"Failed to save or encode screenshot: {str(e)}")

        except Exception as e:
            raise ToolError(f"Screenshot failed: {str(e)}")

    def _win32_screenshot(self):
        """Take a screenshot using Win32 API"""
        # Get handle to primary monitor
        hwin = win32gui.GetDesktopWindow()
        
        # Get monitor size
        width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)

        # Create device context
        hwindc = win32gui.GetWindowDC(hwin)
        srcdc = win32ui.CreateDCFromHandle(hwindc)
        memdc = srcdc.CreateCompatibleDC()
        
        # Create bitmap
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(srcdc, width, height)
        memdc.SelectObject(bmp)
        
        # Copy screen into bitmap
        memdc.BitBlt((0, 0), (width, height), srcdc, (left, top), win32con.SRCCOPY)
        
        # Convert bitmap to PIL Image
        bmpinfo = bmp.GetInfo()
        bmpstr = bmp.GetBitmapBits(True)
        img = Image.frombuffer(
            'RGB',
            (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
            bmpstr, 'raw', 'BGRX', 0, 1
        )

        # Clean up
        win32gui.DeleteObject(bmp.GetHandle())
        memdc.DeleteDC()
        srcdc.DeleteDC()
        win32gui.ReleaseDC(hwin, hwindc)
        
        return img

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
