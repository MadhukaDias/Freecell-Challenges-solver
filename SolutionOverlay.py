import flet as ft
import flet.canvas as cv
import uiautomation as auto
import win32gui
import re
import asyncio
import sys
import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

def get_scale_factor():
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88) # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    except:
        return 0.5

SCALE_FACTOR = get_scale_factor()

def parse_card_name(name):
    """Converts 'Ten of Spades' to (10, 's')"""
    if not name or "empty" in name.lower():
        return None
    match = re.search(r"(Ace|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Jack|Queen|King) of (Hearts|Clubs|Diamonds|Spades)", name)
    if match:
        # We only need this for finding cards in the UI, we can reconstruct basic parsing if needed
        # Or just import mappings. For simplicity, we redefine local map if needed or pass valid strings.
        # But wait, SolutionOverlay uses parse_card_name inside is_card_in_foundation/get_empty_slot_rect
        # so we need NAME_TO_RANK/NAME_TO_SUIT
        pass
    return None

NAME_TO_RANK = {
    'Ace': 1, 'Two': 2, 'Three': 3, 'Four': 4, 'Five': 5, 'Six': 6,
    'Seven': 7, 'Eight': 8, 'Nine': 9, 'Ten': 10, 'Jack': 11, 'Queen': 12, 'King': 13
}
NAME_TO_SUIT = {
    'Hearts': 'h', 'Clubs': 'c', 'Diamonds': 'd', 'Spades': 's'
}

def parse_card_name(name):
    """Converts 'Ten of Spades' to (10, 's')"""
    if not name or "empty" in name.lower():
        return None
    match = re.search(r"(Ace|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Jack|Queen|King) of (Hearts|Clubs|Diamonds|Spades)", name)
    if match:
        rank_str, suit_str = match.groups()
        return (NAME_TO_RANK[rank_str], NAME_TO_SUIT[suit_str])
    return None

def get_sorted_children(control):
    """Gets children and sorts them Left-to-Right (X coordinate)"""
    if not control.Exists(0, 0):
        return []
    children = control.GetChildren()
    children.sort(key=lambda c: c.BoundingRectangle.left)
    return children

class SolutionOverlay:
    def __init__(self, steps):
        print("Initializing Overlay...")
        self.steps = steps
        self.current_step_index = 0
        
        # Cache UI Controls to avoid re-finding them every frame
        self.window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
        self.tableau_group = self.window.GroupControl(AutomationId="Group_Tableau")
        self.freecell_group = self.window.GroupControl(AutomationId="Group_Free")
        self.foundation_group = self.window.GroupControl(AutomationId="Group_Foundation")
        
        # Cache static containers (Columns/Slots) to avoid fetching them every frame
        # We assume the window is visible and these elements exist during init
        self.tableau_columns = []
        self.reserve_slots = []
        self.foundation_piles = []
        
        try:
            if self.tableau_group.Exists(0,0):
                self.tableau_columns = get_sorted_children(self.tableau_group)
            if self.freecell_group.Exists(0,0):
                self.reserve_slots = get_sorted_children(self.freecell_group)
            if self.foundation_group.Exists(0,0):
                self.foundation_piles = get_sorted_children(self.foundation_group)
        except Exception as e:
            print(f"Warning: Could not cache UI elements: {e}")

        # Start Flet App
        ft.app(target=self.main_loop)

    async def main_loop(self, page: ft.Page):
        self.page = page
        page.padding = 0
        page.spacing = 0
        page.window.bgcolor = ft.Colors.TRANSPARENT
        page.bgcolor = ft.Colors.TRANSPARENT
        page.window.title_bar_hidden = True
        page.window.frameless = True
        page.window.always_on_top = True
        page.window.maximized = True
        page.window.ignore_mouse_events = True # Click-through
        
        # Create controls for Source and Dest
        # We use AnimatedContainer for fade effects
        self.src_box_outer = ft.Container(
            border=ft.Border.all(2, ft.Colors.ORANGE),
            border_radius=6,
            animate_opacity=150,
            opacity=0,
            width=0, height=0,
            left=0, top=0,
        )

        self.src_box = ft.Container(
            border=ft.Border.all(3, ft.Colors.AMBER),
            border_radius=6,
            animate_opacity=150,
            opacity=0,
            width=0, height=0,
            left=0, top=0,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=15,
                color=ft.Colors.AMBER,
                blur_style=ft.BlurStyle.OUTER,
            )
        )
        
        self.dest_cv = cv.Canvas(
            shapes=[],
            expand=True
        )
        
        self.dest_box = ft.Container(
            content=self.dest_cv,
            left=0, top=0,
            width=0, height=0,
            opacity=0,
            animate_opacity=150,
            border_radius=6,
            shadow=ft.BoxShadow(
                spread_radius=-6,
                blur_radius=15,
                color=ft.Colors.AMBER,
                blur_style=ft.BlurStyle.OUTER,
            )
        )
        
        self.stack = ft.Stack([self.dest_box, self.src_box, self.src_box_outer], expand=True)
        page.add(self.stack)
        
        # Start the update loop
        while self.current_step_index < len(self.steps):
            await self.update_overlay()
            await asyncio.sleep(0.05) # 20 FPS
        
        # Solved
        pass

    def get_stack_rect(self, top_card_rect, location_hint):
        """Expands rect to include all cards below the top card in the column."""
        class SimpleRect:
            def __init__(self, l, t, r, b):
                self.left, self.top, self.right, self.bottom = l, t, r, b

        try:
            if "Tableau" in location_hint:
                idx = int(location_hint.split()[-1]) - 1
                if 0 <= idx < len(self.tableau_columns):
                    col = self.tableau_columns[idx]
                    children = col.GetChildren()
                    # Sort by Y coordinate to ensure order
                    children.sort(key=lambda c: c.BoundingRectangle.top)
                    
                    # Find index of top_card
                    start_idx = -1
                    for i, child in enumerate(children):
                        cr = child.BoundingRectangle
                        # Match roughly
                        if abs(cr.left - top_card_rect.left) < 10 and abs(cr.top - top_card_rect.top) < 10:
                            start_idx = i
                            break
                    
                    if start_idx != -1:
                        l, t, r, b = top_card_rect.left, top_card_rect.top, top_card_rect.right, top_card_rect.bottom
                        for i in range(start_idx + 1, len(children)):
                            cr = children[i].BoundingRectangle
                            l = min(l, cr.left)
                            t = min(t, cr.top)
                            r = max(r, cr.right)
                            b = max(b, cr.bottom)
                        return SimpleRect(l, t, r, b)
        except:
            pass
        return top_card_rect

    def get_card_rect(self, card_name, location_hint):
        """
        Finds the specific card (e.g. '8S') in the UI.
        Uses location_hint (e.g. 'Tableau 1') to narrow search.
        """
        try:
            if not self.window.Exists(0, 0):
                return None
        except Exception:
            return None
            
        # Convert '8S' to "Eight of Spades"
        rank_map = {'1': 'Ace', '2': 'Two', '3': 'Three', '4': 'Four', '5': 'Five', 
                    '6': 'Six', '7': 'Seven', '8': 'Eight', '9': 'Nine', 'T': 'Ten', 
                    'J': 'Jack', 'Q': 'Queen', 'K': 'King'}
        suit_map = {'H': 'Hearts', 'C': 'Clubs', 'D': 'Diamonds', 'S': 'Spades'}
        
        if len(card_name) < 2: return None
        r_code = card_name[:-1].upper()
        s_code = card_name[-1].upper()
        
        if r_code not in rank_map or s_code not in suit_map:
            return None
            
        full_name = f"{rank_map[r_code]} of {suit_map[s_code]}"
        regex_name = f".*{full_name}.*"
        
        # 1. Targeted Search based on Hint
        if "Tableau" in location_hint:
            try:
                # "Tableau 1" -> index 0
                idx = int(location_hint.split()[-1]) - 1
                if 0 <= idx < len(self.tableau_columns):
                    col = self.tableau_columns[idx]
                    # Search ONLY in this column
                    # Increased depth to 25 to ensure we find cards in deep stacks (nested or flat)
                    card_el = col.Control(RegexName=regex_name, searchDepth=25)
                    if card_el.Exists(0, 0): return card_el.BoundingRectangle
            except:
                pass
            
            # Fallback: If not found in specific column, search entire Tableau group
            # This handles cases where the card might be in transit or index is off
            card_el = self.tableau_group.Control(RegexName=regex_name, searchDepth=25)
            if card_el.Exists(0, 0): return card_el.BoundingRectangle
        
        elif "Reserve" in location_hint:
            # Search ONLY in reserve slots
            # We can search the group, or iterate slots. Group is faster.
            card_el = self.freecell_group.Control(RegexName=regex_name, searchDepth=3)
            if card_el.Exists(0, 0): return card_el.BoundingRectangle

        # 2. Fallback: Optimized Group Search (Only if hint is empty)
        if not location_hint:
            # Tableau (Most likely)
            card_el = self.tableau_group.Control(RegexName=regex_name, searchDepth=5)
            if card_el.Exists(0, 0): return card_el.BoundingRectangle
            
            # Reserve
            card_el = self.freecell_group.Control(RegexName=regex_name, searchDepth=3)
            if card_el.Exists(0, 0): return card_el.BoundingRectangle
            
            # Foundation
            card_el = self.foundation_group.Control(RegexName=regex_name, searchDepth=3)
            if card_el.Exists(0, 0): return card_el.BoundingRectangle

        return None

    def is_card_in_foundation(self, card_name):
        """Checks if a specific card is already in the foundation."""
        if not card_name or len(card_name) < 2: return False
        
        # Parse card
        r_code = card_name[:-1].upper()
        s_code = card_name[-1].upper()
        
        rank_map = {'A': 1, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, 
                    '6': 6, '7': 7, '8': 8, '9': 9, 'T': 10, 
                    'J': 11, 'Q': 12, 'K': 13}
        suit_map_idx = {'H': 0, 'C': 1, 'D': 2, 'S': 3}
        
        if r_code not in rank_map or s_code not in suit_map_idx:
            return False
            
        target_rank = rank_map[r_code]
        pile_idx = suit_map_idx[s_code]
        
        # Check specific pile
        if pile_idx < len(self.foundation_piles):
            pile = self.foundation_piles[pile_idx]
            # Check if the pile's top card is >= target_rank
            children = pile.GetChildren()
            top_name = children[-1].Name if children else pile.Name
            val = parse_card_name(top_name)
            if val:
                current_rank, current_suit = val
                if current_suit.upper() == s_code and current_rank >= target_rank:
                    return True
        return False

    def get_empty_slot_rect(self, location_type, index=None, suit=None, source_card_name=None):
        """Finds an empty slot or specific target card in Tableau, Reserve, or Foundation"""
        try:
            if not self.window.Exists(0, 0): return None
        except Exception:
            return None
        
        if location_type == "Tableau" and index is not None:
            # Use cached columns
            if 0 <= index < len(self.tableau_columns):
                stack = self.tableau_columns[index]
                
                # OPTIMIZATION: If we know the source card, we can find the EXACT target card
                # instead of just the "top" card. This handles stack moves where the target
                # becomes buried.
                if source_card_name:
                    # 1. Calculate Target Rank/Color
                    # Source: 9S (Black 9) -> Target: 10 (Red)
                    r_code = source_card_name[:-1].upper()
                    s_code = source_card_name[-1].upper()
                    
                    rank_map = {'A': 1, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, 
                                '6': 6, '7': 7, '8': 8, '9': 9, 'T': 10, 
                                'J': 11, 'Q': 12, 'K': 13}
                    
                    if r_code in rank_map:
                        src_rank = rank_map[r_code]
                        
                        # If King, target is the empty stack itself
                        if src_rank == 13:
                            return stack.BoundingRectangle
                            
                        target_rank = src_rank + 1
                        is_black = s_code in ['S', 'C']
                        
                        # 2. Search stack for the target card
                        # We look for a card with Rank = target_rank and Color != is_black
                        children = stack.GetChildren()
                        best_match = None
                        best_top = -1
                        
                        for child in children:
                            val = parse_card_name(child.Name)
                            if val:
                                r, s = val
                                child_is_black = s.upper() in ['S', 'C']
                                if r == target_rank and child_is_black != is_black:
                                    # Handle duplicate ranks (e.g. 9S and 9C in same column)
                                    # The valid target is always the one lowest in the stack (highest Y)
                                    try:
                                        c_top = child.BoundingRectangle.top
                                        if c_top > best_top:
                                            best_match = child
                                            best_top = c_top
                                    except:
                                        pass
                        
                        if best_match:
                            return best_match.BoundingRectangle
                        
                        # 3. If target card NOT found, assume move to empty column
                        # (Even if column is not empty now, it means we moved the stack there)
                        return stack.BoundingRectangle

                # Fallback: Just get the top card (last child)
                children = stack.GetChildren()
                if children: return children[-1].BoundingRectangle
                return stack.BoundingRectangle

        elif location_type == "Reserve":
            # Use cached slots
            for slot in self.reserve_slots:
                if "empty" in slot.Name.lower() or not slot.GetChildren():
                    return slot.BoundingRectangle
            if self.reserve_slots: return self.reserve_slots[0].BoundingRectangle
                    
        elif location_type == "Foundation":
            # Use cached piles
            if suit and len(self.foundation_piles) >= 4:
                suit_map = {'H': 0, 'C': 1, 'D': 2, 'S': 3}
                if suit in suit_map:
                    idx = suit_map[suit]
                    if idx < len(self.foundation_piles):
                        return self.foundation_piles[idx].BoundingRectangle
            
            if self.foundation_piles: return self.foundation_piles[0].BoundingRectangle
            
        return None

    def get_column_rect(self, index):
        if 0 <= index < len(self.tableau_columns):
            return self.tableau_columns[index].BoundingRectangle
        return None

    def get_group_rect(self, group_id):
        # Use cached groups based on ID
        if group_id == "Group_Foundation":
            return self.foundation_group.BoundingRectangle
        elif group_id == "Group_Free":
            return self.freecell_group.BoundingRectangle
        elif group_id == "Group_Tableau":
            return self.tableau_group.BoundingRectangle
        return None

    async def update_overlay(self):
        # 1. Check Window State
        # Use cached window control
        try:
            if not self.window.Exists(0, 0):
                return
        except Exception:
            return
            
        if win32gui.IsIconic(self.window.NativeWindowHandle):
            return

        # 2. Draw Current Step (Loop to allow skipping)
        while self.current_step_index < len(self.steps):
            step = self.steps[self.current_step_index]
            
            # Parse Step
            # Capture Source and Dest hints
            # Regex to capture stack size if present
            card_match = re.search(r"Move (?:stack of (\d+) cards \()?([0-9TJQK][SHDC])\)? from (.*?) to (.*)", step)
            
            card_name = None
            stack_size = 1
            source_hint = ""
            dest_hint = ""
            card_suit = None
            
            if card_match:
                if card_match.group(1):
                    stack_size = int(card_match.group(1))
                card_name = card_match.group(2)
                source_hint = card_match.group(3).strip()
                dest_hint = card_match.group(4).strip()
                
                # Normalize Destination Hint
                # If it's just a number "1"-"8", treat as "Tableau N"
                if dest_hint.isdigit() and 1 <= int(dest_hint) <= 8:
                    dest_hint = f"Tableau {dest_hint}"
                
                card_suit = card_name[-1]
            
            src_rect = None
            dest_rect = None
            
            # Find Source Rect (The Card itself)
            if card_name:
                # 1. Try finding card in Source
                src_rect = self.get_card_rect(card_name, source_hint)
                
                # Expand if stack move
                if src_rect and stack_size > 1:
                    src_rect = self.get_stack_rect(src_rect, source_hint)
                
                if not src_rect:
                    # Card not in source. 
                    
                    # A. Check Foundation (Auto-move or Dest=Foundation)
                    if self.is_card_in_foundation(card_name):
                        print(f"Step {self.current_step_index + 1} Skipped: {card_name} is in Foundation.")
                        self.current_step_index += 1
                        self.src_box.opacity = 0
                        self.src_box_outer.opacity = 0
                        self.dest_box.opacity = 0
                        self.page.update()
                        continue

                    # B. Check Destination (if not Foundation)
                    if "Foundation" not in dest_hint:
                        check_dest_rect = self.get_card_rect(card_name, dest_hint)
                        if check_dest_rect:
                            print(f"Step {self.current_step_index + 1} Complete: {card_name} found in destination ({dest_hint}).")
                            self.current_step_index += 1
                            self.src_box.opacity = 0
                            self.src_box_outer.opacity = 0
                            self.dest_box.opacity = 0
                            self.page.update()
                            continue
                            
                    # C. Fallback: Check Foundation again (maybe it was auto-moved there)
                    # This handles cases where dest was Tableau, but game auto-moved it to Foundation immediately
                    if self.is_card_in_foundation(card_name):
                        print(f"Step {self.current_step_index + 1} Skipped (Fallback): {card_name} is in Foundation.")
                        self.current_step_index += 1
                        self.src_box.opacity = 0
                        self.src_box_outer.opacity = 0
                        self.dest_box.opacity = 0
                        self.page.update()
                        continue
            
            # Find Dest Rect (for drawing arrow)
            if "Foundation" in dest_hint:
                dest_rect = self.get_empty_slot_rect("Foundation", suit=card_suit)
            elif "Reserve" in dest_hint:
                dest_rect = self.get_empty_slot_rect("Reserve")
            elif "Tableau" in dest_hint:
                # Extract Tableau Index
                t_match = re.search(r"Tableau (\d+)", dest_hint)
                if t_match:
                    idx = int(t_match.group(1)) - 1
                    # Pass card_name to find the specific target parent card
                    dest_rect = self.get_empty_slot_rect("Tableau", idx, source_card_name=card_name)
            
            if not dest_rect:
                 pass

            # Calculate dynamic outline width based on window width
            win_rect = self.window.BoundingRectangle
            win_width = win_rect.right - win_rect.left
            # Base width 1920. Scale factor.
            scale_ratio = win_width / 1920.0
            # Clamp scale ratio to be reasonable (e.g. 0.5 to 2.0)
            scale_ratio = max(0.5, min(2.0, scale_ratio))
            
            src_border_width = max(1, int(3 * scale_ratio))
            dest_stroke_width = max(1, int(4 * scale_ratio))
            
            # Dynamic Gap
            GAP = max(3, int(5 * scale_ratio))
            
            # Threshold for valid rectangle size
            MIN_SIZE_THRESHOLD = 20

            # Update UI
            if src_rect:
                # 3. Check Completion (Auto-Advance) - CHECK BEFORE DRAWING
                # If the source card is now inside the destination area
                cx = (src_rect.left + src_rect.right) // 2
                cy = (src_rect.top + src_rect.bottom) // 2
                
                is_at_dest = False
                
                if "Foundation" in dest_hint:
                    f_rect = self.get_group_rect("Group_Foundation")
                    if f_rect:
                        if f_rect.left <= cx <= f_rect.right and f_rect.top <= cy <= f_rect.bottom:
                            is_at_dest = True
                        
                elif "Reserve" in dest_hint:
                    r_rect = self.get_group_rect("Group_Free")
                    if r_rect:
                        if r_rect.left <= cx <= r_rect.right and r_rect.top <= cy <= r_rect.bottom:
                            is_at_dest = True
                        
                elif "Tableau" in dest_hint:
                    # Use dest_rect (the specific card/slot we targeted) for precise checking
                    if dest_rect:
                        # Horizontal: Center of source is within width of dest
                        h_aligned = dest_rect.left <= cx <= dest_rect.right
                        
                        # Vertical: Source top should be roughly within the destination card's vertical range
                        # Case 1: Empty Column -> src.top ~= dest.top
                        # Case 2: Stacking -> src.top > dest.top (offset)
                        # We allow src.top to be anywhere from dest.top to dest.bottom
                        # FIX: Add buffer to allow for slight misalignments (especially for empty columns)
                        v_aligned = (dest_rect.top - 50) <= src_rect.top <= (dest_rect.bottom + 50)
                        
                        if h_aligned and v_aligned:
                            is_at_dest = True
                    else:
                        # Fallback if dest_rect wasn't found (e.g. could not read column)
                        t_match = re.search(r"Tableau (\d+)", dest_hint)
                        if t_match:
                            idx = int(t_match.group(1)) - 1
                            c_rect = self.get_column_rect(idx)
                            if c_rect:
                                if c_rect.left <= cx <= c_rect.right and c_rect.top <= cy:
                                    is_at_dest = True
                
                if is_at_dest:
                    print(f"Step {self.current_step_index + 1} Complete: {card_name} detected in destination.")
                    self.current_step_index += 1
                    self.src_box.opacity = 0
                    self.src_box_outer.opacity = 0
                    self.dest_box.opacity = 0
                    self.page.update()
                    # Wait for fade out animation (150ms) to finish before moving to next step position
                    await asyncio.sleep(0.1)
                    continue

                # Update Source Box
                # Apply padding to align perfectly (shrink slightly to fit inside card)
                padding = 0
                s_width = (src_rect.right - src_rect.left - 2*padding) / SCALE_FACTOR
                s_height = (src_rect.bottom - src_rect.top - 2*padding) / SCALE_FACTOR
                
                if s_width < MIN_SIZE_THRESHOLD or s_height < MIN_SIZE_THRESHOLD:
                    self.src_box.opacity = 0
                    self.src_box_outer.opacity = 0
                else:
                    self.src_box.left = (src_rect.left + padding) / SCALE_FACTOR
                    self.src_box.top = (src_rect.top + padding) / SCALE_FACTOR
                    self.src_box.width = s_width
                    self.src_box.height = s_height
                    self.src_box.border = ft.Border.all(src_border_width, ft.Colors.AMBER)
                    self.src_box.opacity = 1
                    
                    # Update Outer Source Box
                    self.src_box_outer.left = self.src_box.left - GAP
                    self.src_box_outer.top = self.src_box.top - GAP
                    self.src_box_outer.width = self.src_box.width + 2*GAP
                    self.src_box_outer.height = self.src_box.height + 2*GAP
                    self.src_box_outer.opacity = 1
                
                # Update Dest Box
                if dest_rect:
                    d_width = (dest_rect.right - dest_rect.left - 2*padding) / SCALE_FACTOR
                    d_height = (dest_rect.bottom - dest_rect.top - 2*padding) / SCALE_FACTOR
                    
                    if d_width < MIN_SIZE_THRESHOLD or d_height < MIN_SIZE_THRESHOLD:
                        self.dest_box.opacity = 0
                    else:
                        # Adjust dest_box to include the outer gap so Canvas covers both rects
                        self.dest_box.left = ((dest_rect.left + padding) / SCALE_FACTOR) - GAP
                        self.dest_box.top = ((dest_rect.top + padding) / SCALE_FACTOR) - GAP
                        self.dest_box.width = d_width + 2*GAP
                        self.dest_box.height = d_height + 2*GAP
                        self.dest_box.opacity = 1
                        
                        # Draw Dotted Rect on Canvas
                        self.dest_cv.shapes = [
                            # Inner Rect (offset by GAP)
                            cv.Rect(
                                GAP, GAP, 
                                d_width, d_height, 
                                border_radius=6,
                                paint=ft.Paint(
                                    style=ft.PaintingStyle.STROKE,
                                    stroke_width=dest_stroke_width,
                                    color=ft.Colors.AMBER,
                                    stroke_dash_pattern=[10, 10]
                                )
                            ),
                            # Outer Rect (at 0,0 covering full box)
                            cv.Rect(
                                0, 0, 
                                self.dest_box.width, self.dest_box.height, 
                                border_radius=6,
                                paint=ft.Paint(
                                    style=ft.PaintingStyle.STROKE,
                                    stroke_width=dest_stroke_width,
                                    color=ft.Colors.ORANGE
                                )
                            )
                        ]
                else:
                    self.dest_box.opacity = 0
                
                self.page.update()
                await asyncio.sleep(0.05) # Wait for fade in

            # If we successfully drew the step (or failed to find dest but didn't skip), break the loop to wait for next frame
            break

def main():
    if len(sys.argv) < 2:
        print("Usage: python SolutionOverlay.py <path_to_steps_file>")
        return

    steps_file = sys.argv[1]
    steps = []
    
    try:
        with open(steps_file, "r") as f:
            steps = [line.strip() for line in f.readlines() if line.strip()]
    except Exception as e:
        print(f"Error reading steps file: {e}")
        return

    if not steps:
        print("No steps found in file.")
        return

    SolutionOverlay(steps)

if __name__ == "__main__":
    main()
