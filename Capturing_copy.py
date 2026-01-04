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
    'Hearts': 'h', 'Diamonds': 'd', 'Clubs': 'c', 'Spades': 's'
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
    match = re.search(r"(Ace|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Jack|Queen|King) of (Hearts|Diamonds|Clubs|Spades)", name)
    if match:
        rank_str, suit_str = match.groups()
        return (NAME_TO_RANK[rank_str], NAME_TO_SUIT[suit_str])
    return None

def get_sorted_children(control):
    """Gets children and sorts them Left-to-Right (X coordinate)"""
    if not control.Exists(0, 1):
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
        window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
        if not window.Exists(0, 0):
            return None
            
        # Parse location: "Tableau 1", "Reserve", "Foundation"
        # Note: Solver output says "Reserve" (generic) or "Foundation" (generic) usually?
        # Let's check solver output again.
        # "Move ... from Reserve to ..." -> Which reserve slot?
        # "Move ... from Tableau 2 to ..."
        
        # We need to find the specific card if possible, or the pile.
        
        tableau_group = window.GroupControl(AutomationId="Group_Tableau")
        freecell_group = window.GroupControl(AutomationId="Group_Free")
        foundation_group = window.GroupControl(AutomationId="Group_Foundation")
        
        target_rect = None
        
        if "Tableau" in location_str:
            # "Tableau 1" -> index 0
            try:
                idx = int(location_str.split()[-1]) - 1
                stacks = get_sorted_children(tableau_group)
                if 0 <= idx < len(stacks):
                    stack = stacks[idx]
                    # We want the TOP card (last child) for Source
                    # Or the empty stack placeholder for Dest
                    cards = get_sorted_children(stack)
                    if cards:
                        target_rect = cards[-1].BoundingRectangle
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
        """
        window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
        if not window.Exists(0, 0):
            return None
            
        # Convert '8S' to "Eight of Spades"
        rank_map = {'1': 'Ace', '2': 'Two', '3': 'Three', '4': 'Four', '5': 'Five', 
                    '6': 'Six', '7': 'Seven', '8': 'Eight', '9': 'Nine', 'T': 'Ten', 
                    'J': 'Jack', 'Q': 'Queen', 'K': 'King'}
        suit_map = {'H': 'Hearts', 'D': 'Diamonds', 'C': 'Clubs', 'S': 'Spades'}
        
        if len(card_name) < 2: return None
        r_code = card_name[:-1].upper()
        s_code = card_name[-1].upper()
        
        if r_code not in rank_map or s_code not in suit_map:
            print(f"Debug: Unknown card code {card_name}")
            return None
            
        full_name = f"{rank_map[r_code]} of {suit_map[s_code]}"
        
        # Use RegexName to handle cases where the name might have suffixes like " - Hint" or " Selected"
        # The glow effect often changes the name or adds a wrapper that affects exact matching.
        regex_name = f".*{full_name}.*"
        
        # Search for this element using a more generic Control type
        # Increase search depth to ensure we find it nested in groups
        card_el = window.Control(RegexName=regex_name, searchDepth=12)
        if card_el.Exists(0, 0):
            return card_el.BoundingRectangle
        
        # Fallback: Try searching specifically in groups if global search fails
        # This can sometimes be faster or find things the global search missed
        for group_id in ["Group_Tableau", "Group_Free", "Group_Foundation"]:
            group = window.GroupControl(AutomationId=group_id)
            if group.Exists(0,0):
                card_el = group.Control(RegexName=regex_name, searchDepth=4)
                if card_el.Exists(0,0):
                    return card_el.BoundingRectangle

        print(f"Debug: Card element '{full_name}' not found via RegexName search.")
        return None

    def get_empty_slot_rect(self, location_type, index=None, suit=None):
        """Finds an empty slot in Tableau, Reserve, or Foundation"""
        window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
        if not window.Exists(0, 0): return None
        
        if location_type == "Tableau" and index is not None:
            tableau_group = window.GroupControl(AutomationId="Group_Tableau")
            stacks = get_sorted_children(tableau_group)
            if 0 <= index < len(stacks):
                # If stack is empty, return stack rect. 
                # If not empty, return top card rect (for stacking)
                cards = get_sorted_children(stacks[index])
                if cards: return cards[-1].BoundingRectangle
                return stacks[index].BoundingRectangle
            else:
                print(f"Debug: Tableau index {index} out of range (0-{len(stacks)-1})")

        elif location_type == "Reserve":
            freecell_group = window.GroupControl(AutomationId="Group_Free")
            slots = get_sorted_children(freecell_group)
            # Try to find an empty slot
            for slot in slots:
                if "empty" in slot.Name.lower() or not slot.GetChildren():
                    return slot.BoundingRectangle
            # If no empty slot found (shouldn't happen if solver says move to reserve), return first slot
            if slots: return slots[0].BoundingRectangle
                    
        elif location_type == "Foundation":
            foundation_group = window.GroupControl(AutomationId="Group_Foundation")
            slots = get_sorted_children(foundation_group)
            
            if suit and len(slots) >= 4:
                # User specified order: Hearts, Clubs, Diamonds, Spades
                suit_map = {'H': 0, 'C': 1, 'D': 2, 'S': 3}
                if suit in suit_map:
                    idx = suit_map[suit]
                    if idx < len(slots):
                        return slots[idx].BoundingRectangle
            
            # Fallback
            if slots: return slots[0].BoundingRectangle
            
        return None

    def get_column_rect(self, index):
        window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
        if not window.Exists(0, 0): return None
        tableau_group = window.GroupControl(AutomationId="Group_Tableau")
        stacks = get_sorted_children(tableau_group)
        if 0 <= index < len(stacks):
            return stacks[index].BoundingRectangle
        return None

    def get_group_rect(self, group_id):
        window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
        if not window.Exists(0, 0): return None
        return window.GroupControl(AutomationId=group_id).BoundingRectangle

    def update_overlay(self):
        if not self.running: return
        
        # 1. Check Window State
        window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
        if not window.Exists(0, 0):
            print("Debug: Solitaire window not found.")
            self.canvas.delete("all")
            self.root.after(500, self.update_overlay)
            return
            
        if win32gui.IsIconic(window.NativeWindowHandle):
            # print("Debug: Window is minimized.") # Commented out to avoid spam
            self.canvas.delete("all")
            self.root.after(100, self.update_overlay)
            return

        # 2. Draw Current Step
        if self.current_step_index < len(self.steps):
            step = self.steps[self.current_step_index]
            
            # Parse Step
            # "Move 8S from Tableau 2 to Tableau 5"
            # "Move 1D from Tableau 2 to Foundation"
            
            src_rect = None
            dest_rect = None
            
            # Extract Card Name (e.g. 8S)
            card_match = re.search(r"Move (?:stack of \d+ cards \()?([0-9TJQK][SHDC])\)? from", step)
            card_name = card_match.group(1) if card_match else None
            card_suit = card_name[-1] if card_name else None
            
            # Find Source Rect (The Card itself)
            if card_name:
                src_rect = self.get_card_rect(card_name, "")
                if not src_rect:
                    print(f"Debug: Could not find source card '{card_name}'")
            
            # Find Dest Rect
            if "to Foundation" in step:
                dest_rect = self.get_empty_slot_rect("Foundation", suit=card_suit)
            elif "to Reserve" in step:
                dest_rect = self.get_empty_slot_rect("Reserve")
            elif "to Tableau" in step:
                # Extract Tableau Index
                t_match = re.search(r"to Tableau (\d+)", step)
                if t_match:
                    idx = int(t_match.group(1)) - 1
                    dest_rect = self.get_empty_slot_rect("Tableau", idx)
            
            if not dest_rect:
                 print(f"Debug: Could not find destination for step: {step}")

            self.canvas.delete("all")
            
            if src_rect:
                print(f"Debug: Drawing overlay for {card_name} at {src_rect}")
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
                # We use the current src_rect which is updated every frame
                cx = (src_rect.left + src_rect.right) // 2
                cy = (src_rect.top + src_rect.bottom) // 2
                
                is_at_dest = False
                
                if "to Foundation" in step:
                    f_rect = self.get_group_rect("Group_Foundation")
                    if f_rect:
                        # Check if inside foundation area
                        if f_rect.left <= cx <= f_rect.right and f_rect.top <= cy <= f_rect.bottom:
                            is_at_dest = True
                        else:
                            # Debug print occasionally
                            # print(f"Debug: Card at ({cx},{cy}) not in Foundation ({f_rect.left},{f_rect.top},{f_rect.right},{f_rect.bottom})")
                            pass
                        
                elif "to Reserve" in step:
                    r_rect = self.get_group_rect("Group_Free")
                    if r_rect:
                        if r_rect.left <= cx <= r_rect.right and r_rect.top <= cy <= r_rect.bottom:
                            is_at_dest = True
                        
                elif "to Tableau" in step:
                    t_match = re.search(r"to Tableau (\d+)", step)
                    if t_match:
                        idx = int(t_match.group(1)) - 1
                        c_rect = self.get_column_rect(idx)
                        # Check if card is within the column's horizontal bounds
                        # and generally in the vertical area (not way above)
                        if c_rect:
                            if c_rect.left <= cx <= c_rect.right and c_rect.top <= cy:
                                is_at_dest = True
                            else:
                                # print(f"Debug: Card at ({cx},{cy}) not in Col {idx} ({c_rect.left},{c_rect.top},{c_rect.right},{c_rect.bottom})")
                                pass
                
                if is_at_dest:
                    print(f"Step {self.current_step_index + 1} Complete: {card_name} detected in destination.")
                    self.current_step_index += 1
                    # Clear canvas immediately to give feedback
                    self.canvas.delete("all")
                    # Allow loop to continue to schedule next update
                    pass

        else:
            self.canvas.delete("all")
            self.canvas.create_text(500, 500, text="Solved!", fill="green", font=("Arial", 30))
            # Draw Close Button
            w = self.root.winfo_screenwidth()
            self.canvas.create_rectangle(w-150, 10, w-10, 50, fill="red", outline="black")
            self.canvas.create_text(w-80, 30, text="Exit", fill="white", font=("Arial", 12, "bold"))
            self.canvas.bind("<Button-1>", lambda e: sys.exit(0))

        self.root.after(50, self.update_overlay)

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