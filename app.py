from flask import Flask, request, send_file, jsonify, abort
from PIL import Image, ImageDraw, ImageFont
import requests
import time
import uuid
from io import BytesIO

app = Flask(__name__)

DEFAULT_LOGO_URL = "https://i.postimg.cc/pTTvjx8r/Group-143.png"
FONT_PATH = "InterTight-Bold.ttf"  # Updated font path

# Store images in memory for a short time:
EPHEMERAL_STORE = {}

# Lifetime in seconds
IMAGE_LIFETIME = 60  # 1 minute

@app.route('/')
def home():
    return "Flask Image Editor is running!"

def wrap_text(draw, text, font, max_width):
    words = text.split()
    if not words:
        return [""]

    lines = []
    current_line = words[0]

    for word in words[1:]:
        test_line = current_line + " " + word
        w, _ = draw.textbbox((0, 0), test_line, font=font)[2:]
        if w <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word

    lines.append(current_line)
    return lines

@app.route('/edit_image', methods=['POST'])
def edit_image():
    """
    1. Generate the edited image with new dimensions (1080x1350).
    2. Store the result in EPHEMERAL_STORE with a UUID.
    3. Return a JSON object containing a temporary URL.
    """
    try:
        data = request.get_json()
        image_url = data.get("image_url")
        text = data.get("text", "Default Text")
        text = text.upper()
        logo_url = data.get("logo_url", DEFAULT_LOGO_URL)

        # Download base image
        response = requests.get(image_url)
        img = Image.open(BytesIO(response.content)).convert("RGB")
        img = img.resize((1080, 1350), Image.LANCZOS)  # Updated size

        # Download and resize the logo
        logo_response = requests.get(logo_url)
        logo = Image.open(BytesIO(logo_response.content)).convert("RGBA")
        logo = logo.resize((185, 58), Image.LANCZOS)

        # Create a vertical gradient for the lower portion (adjusted for new height)
        gradient_height = int(img.height * 0.6)  # Increased gradient coverage to 60% of height
        gradient_col = Image.new('L', (1, gradient_height), 0)
        for y in range(gradient_height):
            alpha = int(230 * (y / float(gradient_height - 1)))
            gradient_col.putpixel((0, y), alpha)
        gradient = gradient_col.resize((img.width, gradient_height))

        # Apply gradient overlay
        gradient_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        black_rect = Image.new("RGBA", (img.width, gradient_height), (0, 0, 0, 255))
        gradient_overlay.paste(black_rect, (0, img.height - gradient_height), gradient)
        img = Image.alpha_composite(img.convert("RGBA"), gradient_overlay)

        # Paste the logo - move to top left corner with padding
        logo_padding = 40
        logo_x = logo_padding
        logo_y = logo_padding
        img.paste(logo, (logo_x, logo_y), logo)

        # Prepare and draw text
        draw = ImageDraw.Draw(img)
        font_size = 80  # Increased font size for better readability
        font = ImageFont.truetype(FONT_PATH, font_size)

        max_text_width = int(img.width * 0.85)
        lines = wrap_text(draw, text, font, max_text_width)
        line_height = draw.textbbox((0, 0), "Ay", font=font)[3]
        num_lines = len(lines)

        # Position text in the bottom section of the image with left alignment
        text_padding = 50
        bottom_padding = 120
        
        total_text_height = line_height * num_lines
        bottom_line_y = img.height - bottom_padding - total_text_height
        
        current_y = bottom_line_y
        for line in lines:
            text_x = text_padding  # Left align text with padding
            draw.text((text_x, current_y), line, font=font, fill=(255, 255, 255, 255))
            current_y += line_height

        # Convert final image to bytes
        output = BytesIO()
        img.convert("RGB").save(output, format="JPEG", quality=90)
        output.seek(0)

        # Generate a unique ID and store the image in memory
        image_id = str(uuid.uuid4())
        EPHEMERAL_STORE[image_id] = {
            "data": output.getvalue(),
            "expires_at": time.time() + IMAGE_LIFETIME
        }

        # Construct a temporary URL for retrieval
        temp_url = request.host_url.rstrip("/") + "/temp_image/" + image_id

        return jsonify({
            "message": "Image generated successfully",
            "temp_image_url": temp_url
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/temp_image/<image_id>', methods=['GET'])
def temp_image(image_id):
    """
    This route returns the stored image if it hasn't expired.
    Otherwise, returns 404.
    """
    # Clean up any expired images before checking
    cleanup_ephemeral_store()

    # Check if the image ID is in the store
    if image_id not in EPHEMERAL_STORE:
        # Not found or already expired/removed
        abort(404, description="Image not found or expired")

    # Retrieve the image data
    image_entry = EPHEMERAL_STORE[image_id]
    # Double-check if it's expired
    if time.time() > image_entry["expires_at"]:
        # Remove from store and 404
        EPHEMERAL_STORE.pop(image_id, None)
        abort(404, description="Image has expired")

    # Return the image as a file
    return send_file(
        BytesIO(image_entry["data"]),
        mimetype='image/jpeg'
    )

def cleanup_ephemeral_store():
    """
    Remove any images that have passed their expiration time.
    This can be called before each request or on a schedule.
    """
    now = time.time()
    expired_keys = [
        key for key, val in EPHEMERAL_STORE.items()
        if now > val["expires_at"]
    ]
    for key in expired_keys:
        EPHEMERAL_STORE.pop(key, None)

if __name__ == '__main__':
    from waitress import serve
    serve(app, host="0.0.0.0", port=10000)
