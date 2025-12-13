import cv2
import numpy as np
import os

# --- CONFIGURATION (Must match your aligned grid) ---
START_X = 87
COL_SPACING = 185
START_Y = 218
VERTICAL_FAN = 51
BOX_WIDTH = 27
BOX_HEIGHT = 44

# --- Top Row Configuration (Freecells & Foundations) ---
TOP_ROW_Y = 8          # Y-coordinate for the top row
FREECELL_START_X = 36  # X-coordinate for first Freecell (aligns with Col 1)
FOUNDATION_START_X = 878 # X-coordinate for first Foundation (aligns with Col 5)
# ----------------------------------------------------

def load_templates():
    """Loads rank and suit images from the assets folder."""
    ranks = {}
    suits = {}
    
    # Load Ranks (A, 2-9, 10, J, Q, K)
    rank_names = ['a', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'j', 'q', 'k']
    for r in rank_names:
        # Note: I kept your path, ensure assets are .jpg as per your last edit
        path = f"C:/Users/madhu/Desktop/Freecell solver - Copy/Code/assets/rank_{r}.jpg"
        if not os.path.exists(path):
            print(f"WARNING: Missing {path}")
            continue
        img = cv2.imread(path, 0)
        ranks[r.upper()] = img

    # Load Suits (h, d, c, s)
    suit_names = ['h', 'd', 'c', 's']
    for s in suit_names:
        path = f"C:/Users/madhu/Desktop/Freecell solver - Copy/Code/assets/suit_{s}.jpg"
        if not os.path.exists(path):
            print(f"WARNING: Missing {path}")
            continue
        img = cv2.imread(path, 0)
        suits[s.upper()] = img
        
    return ranks, suits

def get_best_match(img_gray, templates, threshold=0.8):
    """Finds the best matching template for a given image slice."""
    best_name = None
    best_score = -1
    
    for name, template in templates.items():
        if template.shape[0] > img_gray.shape[0] or template.shape[1] > img_gray.shape[1]:
            continue

        res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        
        if max_val > best_score:
            best_score = max_val
            best_name = name
            
    if best_score >= threshold:
        return best_name
    return None

def detect_single_card(img_gray, x, y, ranks, suits, debug_img=None, color=(255, 0, 0)):
    """Helper to detect a single card at a specific location."""
    if y + BOX_HEIGHT > img_gray.shape[0] or x + BOX_WIDTH > img_gray.shape[1]:
        return None

    roi = img_gray[y : y+BOX_HEIGHT, x : x+BOX_WIDTH]
    
    # Identify Rank
    split_point = int(BOX_HEIGHT * 0.6)
    rank_roi = roi[0:split_point, :]
    suit_roi = roi[split_point:, :]
    
    found_rank = get_best_match(rank_roi, ranks, threshold=0.5)
    found_suit = None
    if found_rank:
        # Identify Suit
        found_suit = get_best_match(suit_roi, suits, threshold=0.75)
    
    if found_rank and found_suit:
        card_code = found_rank + found_suit
        
        if debug_img is not None:
            top_left = (x, y)
            bottom_right = (x + BOX_WIDTH, y + BOX_HEIGHT)
            cv2.rectangle(debug_img, top_left, bottom_right, color, 2)
            cv2.putText(debug_img, card_code, (x, y-5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        return card_code
    else:
        if debug_img is not None:
            top_left = (x, y)
            bottom_right = (x + BOX_WIDTH, y + BOX_HEIGHT)
            cv2.rectangle(debug_img, top_left, bottom_right, (0, 0, 255), 1)
        return None

def read_board(image_path):
    # Load the image
    img = cv2.imread(image_path)
    if img is None:
        print(f"Error: Could not open image at {image_path}")
        return None, None, None, None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Create a copy of the image to draw on (The Debug Image)
    debug_img = img.copy()
    
    ranks, suits = load_templates()
    
    # --- 1. Detect Freecells (Reserve) ---
    freecells = []
    for i in range(4):
        x = FREECELL_START_X + (i * COL_SPACING)
        card = detect_single_card(gray, x, TOP_ROW_Y, ranks, suits, debug_img, color=(255, 255, 0)) # Cyan
        if card:
            freecells.append(card)
        else:
            freecells.append("00") # Empty slot

    # --- 2. Detect Foundations ---
    # We detect what is visible. Note: We don't know which slot is which suit visually 
    # unless we enforce order. We'll just list what we find.
    foundations = [] 
    for i in range(4):
        x = FOUNDATION_START_X + (i * COL_SPACING)
        card = detect_single_card(gray, x, TOP_ROW_Y, ranks, suits, debug_img, color=(255, 0, 255)) # Magenta
        if card:
            foundations.append(card)
        else:
            foundations.append("00")

    # --- 3. Detect Tableau ---
    tableau = []
    
    # Loop through 8 columns
    for col_idx in range(8):
        column_cards = []
        current_x = START_X + (col_idx * COL_SPACING)
        
        # Checking up to 15 rows (Standard Freecell stack height)
        for row_idx in range(15): 
            current_y = START_Y + (row_idx * VERTICAL_FAN)
            
            # Check if we are going off the bottom of the image
            if current_y + BOX_HEIGHT > gray.shape[0]:
                break

            # 1. Slice the Region of Interest (ROI)
            roi = gray[current_y : current_y+BOX_HEIGHT, current_x : current_x+BOX_WIDTH]
            
            # 2. Identify Rank
            split_point = int(BOX_HEIGHT * 0.6)
            rank_roi = roi[0:split_point, :]
            suit_roi = roi[split_point:, :]
            
            found_rank = get_best_match(rank_roi, ranks, threshold=0.5)
            found_suit = None
            if found_rank:
                found_suit = get_best_match(suit_roi, suits, threshold=0.75)
            
            if found_rank and found_suit:
                card_code = found_rank + found_suit 
                column_cards.append(card_code)
                
                # --- VISUALIZATION LOGIC ---
                # Draw a Green Rectangle around the detected card header
                top_left = (current_x, current_y)
                bottom_right = (current_x + BOX_WIDTH, current_y + BOX_HEIGHT)
                cv2.rectangle(debug_img, top_left, bottom_right, (0, 255, 0), 2)
                
                # Write the Card Name (e.g. "KD") in Red above the box
                cv2.putText(debug_img, card_code, (current_x-30, current_y+30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                # ---------------------------
            else:
                # Draw Red Rectangle for failed detection
                top_left = (current_x, current_y)
                bottom_right = (current_x + BOX_WIDTH, current_y + BOX_HEIGHT)
                cv2.rectangle(debug_img, top_left, bottom_right, (0, 0, 255), 1)
                break
                
        tableau.append(column_cards)
        
    return freecells, foundations, tableau, debug_img

if __name__ == "__main__":
    # Define input path
    input_path = "C:/Users/madhu/Desktop/Freecell solver/Test/freecell/Vision/Screenshot 2025-12-14 025648.png"
    
    # Run the reader
    freecells, foundations, tableau, visual_output = read_board(input_path)
    
    if visual_output is not None:
        # 1. Print the text data
        print("Detected Board Configuration:")
        print(f"Freecells: {freecells}")
        print(f"Foundations: {foundations}")
        for i, col in enumerate(tableau):
            print(f"Col {i+1}: {col}")
            
        # 2. Show and Save the visual output
        output_filename = "C:/Users/madhu/Desktop/Freecell solver/Test/freecell/Vision/debug_output.jpg"
        cv2.imwrite(output_filename, visual_output)
        print(f"\nSUCCESS: visual map saved to '{output_filename}'. Open it to verify!")
        
        # --- Generate Encoded String ---
        encoded_str = ""
        
        # 1. Freecells (4 slots)
        for card in freecells:
            # Convert '10' to 't', 'a' to '1', and ensure lowercase
            c = card.lower().replace('10', 't').replace('a', '1')
            encoded_str += c
            
        # 2. Foundations (4 slots)
        for card in foundations:
            c = card.lower().replace('10', 't').replace('a', '1')
            encoded_str += c
            
        # 3. Tableau (8 columns)
        roman_numerals = ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii']
        for idx, col in enumerate(tableau):
            encoded_str += roman_numerals[idx]
            for card in col:
                c = card.lower().replace('10', 't').replace('a', '1')
                encoded_str += c
                
        print(f"\nEncoded String:\n{encoded_str}")

        # Optional: Show a popup window (Press any key to close)
        # cv2.imshow("Debug View", visual_output)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()