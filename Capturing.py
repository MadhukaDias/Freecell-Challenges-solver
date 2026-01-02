import uiautomation as auto
import re
import time
import subprocess
import sys

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
    1: 'a', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 't', 11: 'j', 12: 'q', 13: 'k'
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

# --- 4. MAIN EXECUTION ---

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
            # Assuming solver.exe is in the same directory
            result = subprocess.run(["solver.exe", encoded_string], capture_output=True, text=True)
            print(result.stdout)
            if result.stderr:
                print("Errors:", result.stderr)
        except FileNotFoundError:
            print("Error: solver.exe not found in the current directory.")
        except Exception as e:
            print(f"Error running solver: {e}")
            
    else:
        print("Game window not detected or could not parse state.")

if __name__ == "__main__":
    main()