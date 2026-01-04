import uiautomation as auto
import re
import time
import subprocess
import sys
import os
import tkinter as tk
import win32api
import win32con
import win32gui
import threading

# --- 1. CONFIGURATION & MAPPINGS ---

# Map Text Name to Data (Input from Game)
NAME_TO_RANK = {
    'Ace': 1, 'Two': 2, 'Three': 3, 'Four': 4, 'Five': 5, 'Six': 6,
    'Seven': 7, 'Eight': 8, 'Nine': 9, 'Ten': 10, 'Jack': 11, 'Queen': 12, 'King': 13
}
NAME_TO_SUIT = {
    'Hearts': 'h', 'Clubs': 'c', 'Diamonds': 'd', 'Spades': 's'
}

# Map Data to String Code (Output to Solver)
# 1->'a', 10->'t', 13->'k'
RANK_TO_CODE = {
    1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 't', 11: 'j', 12: 'q', 13: 'k'
}

COLUMN_PREFIXES = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii"]

# --- 2. VISION LOGIC (UI AUTOMATION) ---

def parse_card_name(name):
    """Converts 'Ten of Spades' to (10, 's')"""
    if not name or "empty" in name.lower():
        return None
        
    # Regex to capture rank and suit
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

def scrape_game_state():
    """Scrapes the window and returns a raw dictionary of data"""
    window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
    if not window.Exists(0, 1):
        return None

    # Connect to Groups
    tableau_group = window.GroupControl(AutomationId="Group_Tableau")
    freecell_group = window.GroupControl(AutomationId="Group_Free")
    foundation_group = window.GroupControl(AutomationId="Group_Foundation")

    state = {
        "freecells": [],
        "foundation": [],
        "tableau": []
    }

    # 1. READ FREECELLS (4 slots)
    # We expect 4 children. If < 4, we pad later, but usually Solitaire has 4 fixed slots.
    fc_elements = get_sorted_children(freecell_group)
    for cell in fc_elements:
        card_val = parse_card_name(cell.Name)
        if not card_val:
            # Check inside if the container name is generic
            kids = cell.GetChildren()
            if kids:
                card_val = parse_card_name(kids[0].Name)
        state["freecells"].append(card_val)

    # 2. READ FOUNDATIONS (4 slots)
    found_elements = get_sorted_children(foundation_group)
    for pile in found_elements:
        card_val = parse_card_name(pile.Name)
        if not card_val:
            kids = pile.GetChildren()
            if kids:
                # Top card is the last child
                card_val = parse_card_name(kids[-1].Name)
        state["foundation"].append(card_val)

    # 3. READ TABLEAU (8 columns)
    tab_stacks = get_sorted_children(tableau_group)
    for stack in tab_stacks:
        col_cards = []
        # Sort cards Top-to-Bottom
        card_elements = get_sorted_children(stack)
        card_elements.sort(key=lambda c: c.BoundingRectangle.top)
        
        for card_el in card_elements:
            val = parse_card_name(card_el.Name)
            if val:
                col_cards.append(val)
        state["tableau"].append(col_cards)

    return state

# --- 3. ENCODING LOGIC (THE REQUESTED FORMAT) ---

def encode_card(card_tuple):
    """(10, 's') -> 'ts', None -> '00'"""
    if card_tuple is None:
        return "00"
    rank_int, suit_char = card_tuple
    return f"{RANK_TO_CODE[rank_int]}{suit_char}"

def generate_encoded_string(state):
    """
    Constructs the string: Freecells + Foundation + Tableau(prefixed)
    Ex: 3c5s0000ah0000asits9d...
    """
    
    # 1. Freecells (Ensure exactly 4 slots)
    fc_str = ""
    current_fcs = state['freecells']
    # Pad or trim to ensure exactly 4 items
    for i in range(4):
        if i < len(current_fcs):
            fc_str += encode_card(current_fcs[i])
        else:
            fc_str += "00"

    # 2. Foundation (Ensure exactly 4 slots)
    fo_str = ""
    current_fos = state['foundation']
    for i in range(4):
        if i < len(current_fos):
            fo_str += encode_card(current_fos[i])
        else:
            fo_str += "00"

    # 3. Tableau (Prefix i, ii, iii...)
    tab_str = ""
    for idx, column in enumerate(state['tableau']):
        if idx < 8: # Ensure we don't go out of bounds if UI finds ghost items
            prefix = COLUMN_PREFIXES[idx]
            tab_str += prefix
            for card in column:
                tab_str += encode_card(card)

    return fc_str + fo_str + tab_str

# --- 5. OVERLAY LOGIC ---

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

        self.root = tk.Tk()
        self.root.attributes('-fullscreen', True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.6)
        self.root.attributes('-transparentcolor', 'white')
        self.root.config(bg='white')
        
        # Bind Spacebar to Next Step
        self.root.bind("<space>", self.force_next_step)
        self.root.bind("<Right>", self.force_next_step)
        
        self.canvas = tk.Canvas(self.root, bg='white', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        
        # Add a button-like text for manual advance
        self.canvas.bind("<Button-1>", self.check_button_click)
        
        self.last_click_state = False
        self.running = True
        
        # Start update loop
        self.update_overlay()
        self.root.mainloop()

    def force_next_step(self, event=None):
        if self.current_step_index < len(self.steps):
            print(f"Manual Advance: Skipping Step {self.current_step_index + 1}")
            self.current_step_index += 1
            self.canvas.delete("all")

    def check_button_click(self, event):
        # Check if clicked on "Next Step" button (top right)
        w = self.root.winfo_screenwidth()
        if w - 150 <= event.x <= w - 10 and 10 <= event.y <= 50:
            self.force_next_step()

    def get_element_rect(self, location_str):
        """
        Finds the bounding rect for 'Tableau 1', 'Reserve', 'Foundation'.
        Returns (left, top, right, bottom) or None.
        """
        if not self.window.Exists(0, 0):
            return None
            
        target_rect = None
        
        if "Tableau" in location_str:
            # "Tableau 1" -> index 0
            try:
                idx = int(location_str.split()[-1]) - 1
                if 0 <= idx < len(self.tableau_columns):
                    stack = self.tableau_columns[idx]
                    # We want the TOP card (last child) for Source
                    # Or the empty stack placeholder for Dest
                    children = stack.GetChildren()
                    if children:
                        target_rect = children[-1].BoundingRectangle
                    else:
                        target_rect = stack.BoundingRectangle
            except:
                pass
                
        elif "Reserve" in location_str:
            # Solver output just says "Reserve" usually if moving FROM reserve?
            # Or "Move 8S from Reserve". We can find 8S in reserve.
            # If moving TO reserve, we need an empty slot.
            pass
            
        elif "Foundation" in location_str:
            # "Move ... to Foundation". Any empty foundation slot or matching suit.
            pass
            
        return target_rect

    def get_card_rect(self, card_name, location_hint):
        """
        Finds the specific card (e.g. '8S') in the UI.
        Uses location_hint (e.g. 'Tableau 1') to narrow search.
        """
        if not self.window.Exists(0, 0):
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
        if not self.window.Exists(0, 0): return None
        
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

    def get_foundation_ranks(self):
        """Returns a dict {suit_char_upper: max_rank} for cards currently in foundation."""
        ranks = {'H': 0, 'C': 0, 'D': 0, 'S': 0}
        
        # Use cached piles
        for pile in self.foundation_piles:
            children = pile.GetChildren()
            top_name = children[-1].Name if children else pile.Name
            val = parse_card_name(top_name)
            if val:
                r, s = val
                s_upper = s.upper()
                if r > ranks.get(s_upper, 0):
                    ranks[s_upper] = r
        return ranks

    def parse_step_card_info(self, step_str):
        """Extracts (rank_int, suit_char_upper) from step string like 'Move 8S from...'"""
        card_match = re.search(r"Move (?:stack of \d+ cards \()?([0-9TJQK][SHDC])\)? from", step_str)
        if not card_match: return None
        
        card_code = card_match.group(1) # e.g. '8S'
        if len(card_code) < 2: return None
        
        r_char = card_code[:-1]
        s_char = card_code[-1]
        
        rank_map_inv = {'A': 1, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13}
        r_int = rank_map_inv.get(r_char, 0)
        
        return (r_int, s_char)

    def update_overlay(self):
        if not self.running: return
        
        # 1. Check Window State
        # Use cached window control
        if not self.window.Exists(0, 0):
            # print("Debug: Solitaire window not found.")
            self.canvas.delete("all")
            self.root.after(100, self.update_overlay)
            return
            
        if win32gui.IsIconic(self.window.NativeWindowHandle):
            self.canvas.delete("all")
            self.root.after(100, self.update_overlay)
            return

        # 2. Draw Current Step (Loop to allow skipping)
        while self.current_step_index < len(self.steps):
            step = self.steps[self.current_step_index]
            
            # Parse Step
            # Capture Source and Dest hints
            card_match = re.search(r"Move (?:stack of \d+ cards \()?([0-9TJQK][SHDC])\)? from (.*?) to (.*)", step)
            
            card_name = None
            source_hint = ""
            dest_hint = ""
            card_suit = None
            
            if card_match:
                card_name = card_match.group(1)
                source_hint = card_match.group(2).strip()
                dest_hint = card_match.group(3).strip()
                
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
                
                if not src_rect:
                    # Card not in source. 
                    
                    # A. Check Foundation (Auto-move or Dest=Foundation)
                    if self.is_card_in_foundation(card_name):
                        print(f"Step {self.current_step_index + 1} Skipped: {card_name} is in Foundation.")
                        self.current_step_index += 1
                        self.canvas.delete("all")
                        continue

                    # B. Check Destination (if not Foundation)
                    if "Foundation" not in dest_hint:
                        check_dest_rect = self.get_card_rect(card_name, dest_hint)
                        if check_dest_rect:
                            print(f"Step {self.current_step_index + 1} Complete: {card_name} found in destination ({dest_hint}).")
                            self.current_step_index += 1
                            self.canvas.delete("all")
                            continue
                            
                    # C. Fallback: Check Foundation again (maybe it was auto-moved there)
                    # This handles cases where dest was Tableau, but game auto-moved it to Foundation immediately
                    if self.is_card_in_foundation(card_name):
                        print(f"Step {self.current_step_index + 1} Skipped (Fallback): {card_name} is in Foundation.")
                        self.current_step_index += 1
                        self.canvas.delete("all")
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

            self.canvas.delete("all")
            
            if src_rect:
                # Draw Box around Source
                x1, y1, x2, y2 = src_rect.left, src_rect.top, src_rect.right, src_rect.bottom
                self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=3)
                
                # Draw Arrow to Dest
                if dest_rect:
                    dx1, dy1, dx2, dy2 = dest_rect.left, dest_rect.top, dest_rect.right, dest_rect.bottom
                    cx_src, cy_src = (x1+x2)/2, (y1+y2)/2
                    cx_dest, cy_dest = (dx1+dx2)/2, (dy1+dy2)/2
                    self.canvas.create_line(cx_src, cy_src, cx_dest, cy_dest, fill="red", width=3, arrow=tk.LAST)
                
                # Draw Text
                self.canvas.create_text(x1, y1-20, text=step, fill="red", font=("Arial", 14, "bold"), anchor="w")
                
                # Draw "Next Step" Button
                w = self.root.winfo_screenwidth()
                self.canvas.create_rectangle(w-150, 10, w-10, 50, fill="lightgray", outline="black")
                self.canvas.create_text(w-80, 30, text="Next Step >>", fill="black", font=("Arial", 12, "bold"))

                # 3. Check Completion (Auto-Advance)
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
                        v_aligned = dest_rect.top <= src_rect.top <= dest_rect.bottom
                        
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
                    self.canvas.delete("all")
                    continue

            # If we successfully drew the step (or failed to find dest but didn't skip), break the loop to wait for next frame
            break

        else:
            # Loop finished (index >= len)
            self.canvas.delete("all")
            self.canvas.create_text(500, 500, text="Solved!", fill="green", font=("Arial", 30))
            # Draw Close Button
            w = self.root.winfo_screenwidth()
            self.canvas.create_rectangle(w-150, 10, w-10, 50, fill="red", outline="black")
            self.canvas.create_text(w-80, 30, text="Exit", fill="white", font=("Arial", 12, "bold"))
            self.canvas.bind("<Button-1>", lambda e: sys.exit(0))

        self.root.after(1, self.update_overlay)

# --- 6. MAIN EXECUTION ---

def main():
    print("Solitaire Encoder Running...")
    print("Make sure Microsoft Solitaire Collection is open and visible.")
    print("-" * 50)

    # 1. Get raw data
    state = scrape_game_state()
    
    if state:
        # 2. Encode to string
        encoded_string = generate_encoded_string(state)
        print(f"\nCaptured State:")
        print(encoded_string)
        
        # 3. Call Solver
        print("\nRunning Solver...")
        try:
            # Use relative path to solver.exe
            solver_path = os.path.join(os.path.dirname(__file__), "Test", "freecell", "solver", "solver.exe")
            print(f"Solver Path: {os.path.abspath(solver_path)}")
            result = subprocess.run([solver_path, encoded_string], capture_output=True, text=True)
            output = result.stdout
            print("--- Raw Solver Output ---")
            print(output)
            print("-------------------------")
            
            # Parse Steps
            steps = []
            for line in output.splitlines():
                # Strip ANSI codes
                clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line)
                
                if clean_line.startswith("Step"):
                    steps.append(clean_line.strip())
            
            if steps:
                print(f"Found {len(steps)} steps. Starting Overlay...")
                SolutionOverlay(steps)
            else:
                print("No solution found or parsing failed.")
                print(output)

        except FileNotFoundError:
            print("Error: solver.exe not found in the current directory.")
        except Exception as e:
            print(f"Error running solver: {e}")
            
    else:
        print("Game window not detected or could not parse state.")

if __name__ == "__main__":
    main()