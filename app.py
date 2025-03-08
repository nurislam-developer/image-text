from flask import Flask, request, send_file, jsonify, abort
from PIL import Image, ImageDraw, ImageFont
import requests
import time
import uuid
from io import BytesIO

app = Flask(__name__)

DEFAULT_LOGO_URL = "https://i.postimg.cc/pLmxYnmy/image-1.png"
FONT_PATH = "Montserrat-Bold.ttf"

# Store images in memory for a short time:
#  key: str (UUID)
#  value: {
#    "data": bytes,
#    "expires_at": float (timestamp)
#  }
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
    1. Generate the edited image (same logic).
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
        img = img.resize((1080, 1080), Image.LANCZOS)

        # Download and resize the logo
        logo_response = requests.get(logo_url)
        logo = Image.open(BytesIO(logo_response.content)).convert("RGBA")
        logo = logo.resize((252, 44), Image.LANCZOS)

        # Create a vertical gradient for the bottom half
        half_height = img.height // 2
        gradient_col = Image.new('L', (1, half_height), 0)
        for y in range(half_height):
            alpha = int(230 * (y / float(half_height - 1)))
            gradient_col.putpixel((0, y), alpha)
        gradient = gradient_col.resize((img.width, half_height))

       

        # # Apply gradient overlay
        gradient_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        black_rect = Image.new("RGBA", (img.width, half_height), (0, 0, 0, 255))
        gradient_overlay.paste(black_rect, (0, img.height - half_height), gradient)
        img = Image.alpha_composite(img.convert("RGBA"), gradient_overlay)


        # Increase gradient height to 80% of the image height
        # gradient_height = int(img.height * 0.8)

        # # Create the gradient overlay
        # gradient_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        # black_rect = Image.new("RGBA", (img.width, gradient_height), (0, 0, 0, 255))
        # gradient_overlay.paste(black_rect, (0, img.height - gradient_height), gradient)
        
        # # Apply the new gradient
        # img = Image.alpha_composite(img.convert("RGBA"), gradient_overlay)

        

        # Paste the logo
        logo_x = (img.width - logo.width) // 2
        logo_y = img.height - logo.height - 50
        img.paste(logo, (logo_x, logo_y), logo)

        # Prepare and draw text
        draw = ImageDraw.Draw(img)
        font_size = 54
        font = ImageFont.truetype(FONT_PATH, font_size)

        max_text_width = int(img.width * 0.85)
        lines = wrap_text(draw, text, font, max_text_width)
        line_height = draw.textbbox((0, 0), "Ay", font=font)[3]
        num_lines = len(lines)

        total_text_height = line_height * num_lines
        bottom_line_y = logo_y - 60 - line_height
        top_line_y = bottom_line_y - (num_lines - 1) * line_height

        current_y = top_line_y
        for line in lines:
            text_width, _ = draw.textbbox((0, 0), line, font=font)[2:]
            text_x = (img.width - text_width) // 2
            draw.text((text_x, current_y), line, font=font, fill=(255, 255, 255, 255))
            current_y += line_height

        # 6. Draw a rectangle (5px height, 80% width) in the gap between text and logo
        rect_width = int(img.width * 0.65)
        rect_height = 8
        rect_color = "#9B050B"

        # Midpoint of the gap between bottom line of text and logo
        # gap_mid = (bottom_line_y + logo_y) // 2
        # rect_y = gap_mid - (rect_height // 2)
        # rect_x = (img.width - rect_width) // 2

        # draw.rectangle(
        #     [rect_x, rect_y, rect_x + rect_width, rect_y + rect_height],
        #     fill=rect_color
        # )

        # Choose a fraction between 0 and 1; higher = closer to the logo
        fraction = 0.7

        gap_mid = bottom_line_y + int((logo_y - bottom_line_y) * fraction)
        rect_y = gap_mid - (rect_height // 2)
        rect_x = (img.width - rect_width) // 2

        draw.rectangle(
            [rect_x, rect_y, rect_x + rect_width, rect_y + rect_height],
            fill=rect_color
        )

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
        # e.g. https://your-railway-app.com/temp_image/<image_id>
        # or if testing locally: http://127.0.0.1:10000/temp_image/<image_id>
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
