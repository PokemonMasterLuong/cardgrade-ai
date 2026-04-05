#!/usr/bin/env python3
"""
Trading Card PSA Grader
Analyzes trading card images and provides PSA-style grades using Claude's vision 1111.
"""

import anthropic
import base64
import sys
import os
from pathlib import Path


PSA_GRADING_SYSTEM = """You are an expert trading card grader with decades of experience grading cards
for PSA (Professional Sports Authenticator) and Beckett (BGS). You evaluate cards with precision
and consistency, using an enhanced grading scale that includes half-point grades and a Pristine tier.

GRADING SCALE:
- Pristine 10: Absolutely flawless. Perfect centering (50/50), razor-sharp corners, flawless edges,
  zero surface defects, full original gloss. Exceptionally rare.
- 10 (Gem Mint): Perfect card. Four sharp corners, no stains, no print defects.
  Virtually perfect centering (55/45 or better). Gloss and original sheen intact.
- 9.5: Between Mint and Gem Mint. Essentially perfect but with one very minor flaw
  not quite meeting PSA 10 standards.
- 9 (Mint): Only one minor flaw allowed. Near-perfect corners, edges, surface.
  Centering 60/40 or better. Very minor printing imperfections allowed.
- 8.5: Between NM-MT and Mint. Strong card with very minor issues on two criteria.
- 8 (NM-MT Near Mint-Mint): Minor imperfections visible only on close inspection.
  75/25 or better centering. Slight surface wear acceptable.
- 7.5: Between NM and NM-MT.
- 7 (NM Near Mint): Minor faults. No major defects. 75/25 centering or better.
  Light surface wear visible. Corners show minor wear.
- 6.5: Between EX-MT and NM.
- 6 (EX-MT Excellent-Mint): Slight surface wear on major surfaces. Slight notching
  on corners. 80/20 centering or better.
- 5.5: Between EX and EX-MT.
- 5 (EX Excellent): Surface wear visible. Corners are slightly rounded. Possible
  minor surface scratches. 85/15 centering or better.
- 4.5: Between VG-EX and EX.
- 4 (VG-EX Very Good-Excellent): Moderate surface wear. Some scuffing. Corner
  rounding. 85/15 centering.
- 3 (VG Very Good): Heavy surface wear, light creases possible. Corners are well
  rounded. Mild staining. 90/10 centering.
- 2 (Good): Heavy wear. Creases. Possibly rounded corners. Heavy staining. Notching on edges.
- 1 (Poor): Heavily worn, badly miscut, altered, or damaged card.

GRADING CRITERIA TO ASSESS:
1. CENTERING: Measure the border ratio front and back (left/right and top/bottom)
2. CORNERS: Examine all four corners for wear, fraying, or damage
3. EDGES: Check all four edges for nicks, chips, or roughness
4. SURFACE: Look for scratches, print lines, stains, creases, or loss of gloss

Provide a detailed, professional grading report with:
- Overall grade (use the scale above, e.g. "Pristine 10", "9.5", "8", etc.)
- Sub-grades for centering, corners, edges, and surface (each on the same scale)
- Specific observations for each category
- Key factors that determined the final grade
- Authenticity assessment based on visible characteristics
- Authenticity assessment based on visible characteristics
"""


def load_image_as_base64(image_path: str) -> tuple[str, str]:
    """Load an image file and return base64 encoded data and media type."""
    path = Path(image_path)

    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    extension = path.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    media_type = media_type_map.get(extension)
    if not media_type:
        raise ValueError(f"Unsupported image format: {extension}. Use JPG, PNG, GIF, or WebP.")

    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    return image_data, media_type


def grade_card(image_path: str, card_description: str = "") -> str:
    """
    Grade a trading card from an image file.

    Args:
        image_path: Path to the card image file
        card_description: Optional description of the card (e.g., "1952 Topps Mickey Mantle #311")

    Returns:
        Detailed grading report as a string
    """
    client = anthropic.Anthropic()

    print(f"Loading image: {image_path}")
    image_data, media_type = load_image_as_base64(image_path)

    user_message = "Please provide a complete PSA-style grading analysis for this trading card."
    if card_description:
        user_message += f"\n\nCard details: {card_description}"

    print("Analyzing card with Claude... (this may take a moment)\n")

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=PSA_GRADING_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": user_message,
                    },
                ],
            }
        ],
    ) as stream:
        report_parts = []
        for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    print(event.delta.text, end="", flush=True)
                    report_parts.append(event.delta.text)

        print()  # newline after streaming
        return "".join(report_parts)


def main():
    print("=" * 60)
    print("  TRADING CARD PSA GRADER - Powered by Claude AI")
    print("=" * 60)
    print()

    # Get image path
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        card_description = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
    else:
        image_path = input("Enter path to card image (JPG/PNG/WebP): ").strip()
        card_description = input("Card description (optional, e.g. '1986 Fleer Michael Jordan #57'): ").strip()

    if not image_path:
        print("Error: No image path provided.")
        sys.exit(1)

    try:
        report = grade_card(image_path, card_description)

        print("\n" + "=" * 60)
        print("  GRADING COMPLETE")
        print("=" * 60)

    except FileNotFoundError as e:
        print(f"\nError: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"\nError: {e}")
        sys.exit(1)
    except anthropic.AuthenticationError:
        print("\nError: Invalid API key. Set your ANTHROPIC_API_KEY environment variable.")
        sys.exit(1)
    except anthropic.APIError as e:
        print(f"\nAPI Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
