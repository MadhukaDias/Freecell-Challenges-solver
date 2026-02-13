import uiautomation as auto
import re
import time
import subprocess
import sys
import os
import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# --- CONFIGURATION & MAPPINGS ---

NAME_TO_RANK = {
    'Ace': 1, 'Two': 2, 'Three': 3, 'Four': 4, 'Five': 5, 'Six': 6,
    'Seven': 7, 'Eight': 8, 'Nine': 9, 'Ten': 10, 'Jack': 11, 'Queen': 12, 'King': 13
}
NAME_TO_SUIT = {
    'Hearts': 'h', 'Clubs': 'c', 'Diamonds': 'd', 'Spades': 's'
}

NAME_TO_RANK_PLURAL = {
    'Aces': 1, 'Twos': 2, 'Threes': 3, 'Fours': 4, 'Fives': 5, 'Sixes': 6,
    'Sevens': 7, 'Eights': 8, 'Nines': 9, 'Tens': 10, 'Jacks': 11, 'Queens': 12, 'Kings': 13
}

RANK_TO_CODE = {
    1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 't', 11: 'j', 12: 'q', 13: 'k'
}

COLUMN_PREFIXES = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii"]

# --- VISION LOGIC ---

def parse_card_name(name):
    if not name or "empty" in name.lower():
        return None
    match = re.search(r"(Ace|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Jack|Queen|King) of (Hearts|Clubs|Diamonds|Spades)", name)
    if match:
        rank_str, suit_str = match.groups()
        return (NAME_TO_RANK[rank_str], NAME_TO_SUIT[suit_str])
    return None

def get_sorted_children(control):
    if not control.Exists(0, 0):
        return []
    children = control.GetChildren()
    children.sort(key=lambda c: c.BoundingRectangle.left)
    return children

def scrape_challenge_info(window):
    challenge_code = "00"
    moves_limit = "0"
    
    # 1. Search for Moves Limit
    moves_el = window.Control(RegexName=r"Moves: \d+", searchDepth=10)
    if moves_el.Exists(0, 0):
        m = re.search(r"Moves: (\d+)", moves_el.Name)
        if m:
            moves_limit = m.group(1)
            
    found_challenge = False
    
    patterns = [
        r".*cleared.*",
        r".*Clear.*",
        r".*Solve.*"
    ]
    
    for pattern in patterns:
        if found_challenge: break
        
        challenge_el = window.Control(RegexName=pattern, searchDepth=15)
        if challenge_el.Exists(0, 0):
            text = challenge_el.Name
            
            # Case A: Specific Card "Clear 10 of Clubs"
            match_specific = re.search(r"Clear (Ace|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Jack|Queen|King|\d+) of (Hearts|Clubs|Diamonds|Spades)", text, re.IGNORECASE)
            if match_specific:
                rank_str = match_specific.group(1)
                suit_str = match_specific.group(2)
                
                if rank_str.isdigit():
                    r_int = int(rank_str)
                else:
                    r_int = NAME_TO_RANK.get(rank_str.capitalize(), 0)
                    
                s_char = NAME_TO_SUIT.get(suit_str.capitalize(), 'h')
                if r_int > 0:
                    challenge_code = f"{RANK_TO_CODE[r_int]}{s_char}"
                    found_challenge = True
                    break

            # Case C: "Clear the [Rank][Symbol]"
            match_symbol = re.search(r"Clear the ([A-Z0-9]+)\s*(.)", text, re.IGNORECASE)
            if match_symbol:
                rank_str = match_symbol.group(1)
                suit_char = match_symbol.group(2)
                
                if rank_str.isdigit():
                    r_int = int(rank_str)
                else:
                    rank_map = {'A':1, 'J':11, 'Q':12, 'K':13}
                    r_int = rank_map.get(rank_str.upper(), 0)
                
                s_char = 'x'
                ord_val = ord(suit_char)
                
                if suit_char == '󰀁' or ord_val == 0xF0001:
                    s_char = 'c'
                elif suit_char == '󰀂' or ord_val == 0xF0002:
                    s_char = 'd'
                elif suit_char == '󰀃' or ord_val == 0xF0003:
                    s_char = 'h'
                elif suit_char == '󰀄' or ord_val == 0xF0004:
                    s_char = 's'
                
                if r_int > 0 and s_char != 'x':
                    challenge_code = f"{RANK_TO_CODE[r_int]}{s_char}"
                    found_challenge = True
                    break

            # Case B: "Sixes cleared" (Count might be in sibling)
            match_plural = re.search(r"(Aces|Twos|Threes|Fours|Fives|Sixes|Sevens|Eights|Nines|Tens|Jacks|Queens|Kings) cleared", text, re.IGNORECASE)
            if match_plural:
                rank_plural = match_plural.group(1)
                try:
                    parent = challenge_el.GetParentControl()
                    siblings = parent.GetChildren()
                    
                    my_idx = -1
                    for i, sib in enumerate(siblings):
                        if sib.GetRuntimeId() == challenge_el.GetRuntimeId():
                            my_idx = i
                            break
                    
                    if my_idx != -1 and my_idx + 1 < len(siblings):
                        next_sib = siblings[my_idx+1]
                        m_count = re.search(r"\d+/(\d+)", next_sib.Name)
                        if m_count:
                            count = m_count.group(1)
                            r_int = NAME_TO_RANK_PLURAL.get(rank_plural.capitalize(), 0)
                            if r_int > 0:
                                challenge_code = f"{RANK_TO_CODE[r_int]}{count}"
                                found_challenge = True
                                break
                except Exception as e:
                    print(f"Debug: Error finding sibling count: {e}")
                
                if found_challenge: break
                
                m_inline = re.search(r"cleared \d+/(\d+)", text, re.IGNORECASE)
                if m_inline:
                    count = m_inline.group(1)
                    r_int = NAME_TO_RANK_PLURAL.get(rank_plural.capitalize(), 0)
                    if r_int > 0:
                        challenge_code = f"{RANK_TO_CODE[r_int]}{count}"
                        found_challenge = True
                        break

            # Case C: "Clear 4 Kings"
            match_count = re.search(r"Clear (\d+) (Aces|Twos|Threes|Fours|Fives|Sixes|Sevens|Eights|Nines|Tens|Jacks|Queens|Kings)", text, re.IGNORECASE)
            if match_count:
                count = match_count.group(1)
                rank_plural = match_count.group(2)
                
                r_int = NAME_TO_RANK_PLURAL.get(rank_plural.capitalize(), 0)
                if r_int > 0:
                    challenge_code = f"{RANK_TO_CODE[r_int]}{count}"
                    found_challenge = True
                    break

    if not found_challenge:
        # Case D: "Twos" and "0/3" separated, without "Clear" keyword
        for plural in NAME_TO_RANK_PLURAL.keys():
            el_plural = window.Control(Name=plural, searchDepth=15) 
            if el_plural.Exists(0,0):
                try:
                    parent = el_plural.GetParentControl()
                    siblings = parent.GetChildren()
                    
                    my_idx = -1
                    for i, sib in enumerate(siblings):
                        if sib.GetRuntimeId() == el_plural.GetRuntimeId():
                            my_idx = i
                            break
                    
                    # Check next sibling
                    if my_idx != -1 and my_idx + 1 < len(siblings):
                        next_sib = siblings[my_idx+1]
                        m_count = re.search(r"\d+/(\d+)", next_sib.Name)
                        if m_count:
                            count = m_count.group(1)
                            r_int = NAME_TO_RANK_PLURAL.get(plural, 0)
                            if r_int > 0:
                                challenge_code = f"{RANK_TO_CODE[r_int]}{count}"
                                found_challenge = True
                                break
                except Exception as e:
                    print(f"Debug: Error in Case D: {e}")
            if found_challenge:
                break

    return challenge_code, moves_limit

def scrape_game_state():
    """Scrapes the window and returns a raw dictionary of data"""
    # Force focus to Solitaire
    window = auto.WindowControl(searchDepth=1, RegexName=".*Solitaire.*")
    if not window.Exists(0, 1):
        return None
    
    # window.SetFocus() 

    # Scrape Challenge Info
    challenge_code, moves_limit = scrape_challenge_info(window)

    # Connect to Groups
    tableau_group = window.GroupControl(AutomationId="Group_Tableau")
    freecell_group = window.GroupControl(AutomationId="Group_Free")
    foundation_group = window.GroupControl(AutomationId="Group_Foundation")

    state = {
        "freecells": [],
        "foundation": [],
        "tableau": [],
        "challenge": challenge_code,
        "moves": moves_limit
    }

    # 1. READ FREECELLS
    fc_elements = get_sorted_children(freecell_group)
    for cell in fc_elements:
        card_val = parse_card_name(cell.Name)
        if not card_val:
            kids = cell.GetChildren()
            if kids:
                card_val = parse_card_name(kids[0].Name)
        state["freecells"].append(card_val)

    # 2. READ FOUNDATIONS
    found_elements = get_sorted_children(foundation_group)
    for pile in found_elements:
        card_val = parse_card_name(pile.Name)
        if not card_val:
            kids = pile.GetChildren()
            if kids:
                card_val = parse_card_name(kids[-1].Name)
        state["foundation"].append(card_val)

    # 3. READ TABLEAU
    tab_stacks = get_sorted_children(tableau_group)
    for stack in tab_stacks:
        col_cards = []
        card_elements = get_sorted_children(stack)
        card_elements.sort(key=lambda c: c.BoundingRectangle.top)
        
        for card_el in card_elements:
            val = parse_card_name(card_el.Name)
            if val:
                col_cards.append(val)
        state["tableau"].append(col_cards)

    return state

def encode_card(card_tuple):
    if card_tuple is None:
        return "00"
    rank_int, suit_char = card_tuple
    return f"{RANK_TO_CODE[rank_int]}{suit_char}"

def generate_encoded_string(state):
    # 1. Freecells
    fc_str = ""
    current_fcs = state['freecells']
    for i in range(4):
        if i < len(current_fcs):
            fc_str += encode_card(current_fcs[i])
        else:
            fc_str += "00"

    # 2. Foundation
    fo_str = ""
    current_fos = state['foundation']
    for i in range(4):
        if i < len(current_fos):
            fo_str += encode_card(current_fos[i])
        else:
            fo_str += "00"

    # 3. Tableau
    tab_str = ""
    for idx, column in enumerate(state['tableau']):
        if idx < 8:
            prefix = COLUMN_PREFIXES[idx]
            tab_str += prefix
            for card in column:
                tab_str += encode_card(card)

    # 4. Challenge Info
    challenge_str = f"${state.get('challenge', '00')}${state.get('moves', '0')}"

    return fc_str + fo_str + tab_str + challenge_str

def main():
    print("Solitaire Capture & Solve running...")
    
    state = scrape_game_state()
    
    if state:
        encoded_string = generate_encoded_string(state)
        
        # Remove any backticks (PowerShell escape characters) that might have gotten into the string
        encoded_string = encoded_string.replace('`', '')
        
        print(f"\nCaptured State:")
        print(encoded_string)
        
        print("\nRunning Solver...")
        try:
            solver_path = os.path.join(os.path.dirname(__file__), "Test", "freecell", "solver", "solver.exe")
            print(f"Solver Path: {os.path.abspath(solver_path)}")
            
            # Run Solver
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
                print(f"Found {len(steps)} steps.")
                
                # Write to file
                steps_file = os.path.join(os.path.dirname(__file__), "current_solution.txt")
                with open(steps_file, "w") as f:
                    for step in steps:
                        f.write(step + "\n")
                
                print(f"Solution saved to {steps_file}")
                
                # Launch Overlay
                overlay_script = os.path.join(os.path.dirname(__file__), "SolutionOverlay.py")
                print("Launching Overlay...")
                subprocess.Popen(["python", overlay_script, steps_file])
                
            else:
                print("No solution found or parsing failed.")

        except FileNotFoundError:
            print("Error: solver.exe not found.")
        except Exception as e:
            print(f"Error running solver: {e}")

if __name__ == "__main__":
    main()
