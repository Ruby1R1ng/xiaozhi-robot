"""Render-derived crop for independent formula recognition (not a PDF modification)."""
from PIL import Image
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'tmp'
im=Image.open(root/'xie-guo-03.png')
print(im.size)
# Region of Theorem 2.1, inspected on original rendered page.
im.crop((680,295,1330,815)).save(root/'theorem-2-1.png')
im.crop((862,354,995,398)).resize((798,264)).save(root/'constant-formula.png')
