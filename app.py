import cv2
import easyocr
import re
import json
import numpy as np
import shutil
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
import os

app = FastAPI()

def extract_clean_text(image_path, reader):
    image = cv2.imread(image_path)
    results = reader.readtext(image, detail=0, paragraph=True)

    lines = [line.strip() for line in results if line.strip()]
    full_text = ' '.join(lines)
    full_text_lower = full_text.lower()

    return full_text, full_text_lower, lines

def check_if_out_of_range(test_value, reference_range):
    try:
        value = float(test_value.replace(',', '.'))
        if '-' in reference_range:
            bounds = reference_range.split('-')
            lower = float(bounds[0].replace(',', '.'))
            upper = float(bounds[1].replace(',', '.'))
            return value < lower or value > upper
        return False
    except (ValueError, IndexError):
        return False

def extract_lab_tests(text, text_lower, lines):
    lab_tests = []

    patterns = [
        r'([A-Za-z\s\(\)]+):\s*([0-9\.,]+)\s*([a-zA-Z%/]+)?\s*\(([0-9\.,\-\s]+)\)',
        r'([A-Za-z\s\(\)]+)\s+([0-9\.,]+)\s*([a-zA-Z%/]+)?\s+([0-9\.,\-\s]+)',
        r'([A-Za-z\s\(\)]+):\s*([0-9\.,]+)\s*\(([0-9\.,\-\s]+)\)',
        r'([A-Za-z\s\(\)]+)\s+([0-9\.,]+)\s+([0-9\.,\-\s]+)',
    ]

    for line in lines:
        for pattern in patterns:
            matches = re.finditer(pattern, line)
            for match in matches:
                groups = match.groups()
                test_name = groups[0].strip()
                test_value = groups[1].strip()
                if len(groups) == 4:
                    test_unit = groups[2].strip() if groups[2] else ""
                    ref_range = groups[3].strip()
                else:
                    test_unit = ""
                    ref_range = groups[2].strip()
                ref_range = ref_range.replace(' ', '')
                out_of_range = check_if_out_of_range(test_value, ref_range)

                lab_tests.append({
                    "test_name": test_name,
                    "test_value": test_value,
                    "bio_reference_range": ref_range,
                    "test_unit": test_unit,
                    "lab_test_out_of_range": out_of_range
                })

    if not lab_tests:
        lab_tests = extract_using_specialized_patterns(text, lines)

    return lab_tests

def extract_using_specialized_patterns(text, lines):
    lab_tests = []
    test_name_pattern = r'([A-Z][A-Za-z\s\(\)]{2,})'
    value_pattern = r'([0-9\.,]+)\s*([a-zA-Z%/]+)?'
    range_pattern = r'([0-9\.,]+\s*-\s*[0-9\.,]+)'

    for i, line in enumerate(lines):
        test_names = re.finditer(test_name_pattern, line)
        for test_match in test_names:
            test_name = test_match.group(1).strip()
            if test_name.lower() in ['test', 'name', 'value', 'range', 'result', 'parameter']:
                continue

            remainder = line[test_match.end():]
            value_matches = re.search(value_pattern, remainder)
            test_value = ""
            test_unit = ""
            ref_range = ""

            if value_matches:
                test_value = value_matches.group(1).strip()
                test_unit = value_matches.group(2).strip() if value_matches.group(2) else ""
                range_match = re.search(range_pattern, remainder)
                if range_match:
                    ref_range = range_match.group(1).strip()
            elif i + 1 < len(lines):
                next_line = lines[i + 1]
                value_matches = re.search(value_pattern, next_line)
                if value_matches:
                    test_value = value_matches.group(1).strip()
                    test_unit = value_matches.group(2).strip() if value_matches.group(2) else ""
                    range_match = re.search(range_pattern, next_line)
                    if range_match:
                        ref_range = range_match.group(1).strip()

            if test_value:
                ref_range = ref_range.replace(' ', '')
                out_of_range = check_if_out_of_range(test_value, ref_range)
                lab_tests.append({
                    "test_name": test_name,
                    "test_value": test_value,
                    "bio_reference_range": ref_range,
                    "test_unit": test_unit,
                    "lab_test_out_of_range": out_of_range
                })

    return lab_tests

def process_lab_report(image_path, reader):
    full_text, full_text_lower, lines = extract_clean_text(image_path, reader)
    lab_tests = extract_lab_tests(full_text, full_text_lower, lines)
    return {
        "is_success": True if lab_tests else False,
        "data": lab_tests
    }

@app.post("/get-lab-tests")
async def get_lab_tests(file: UploadFile = File(...)):
    # Save the uploaded image to a temp file
    temp_dir = "/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, file.filename)

    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # Load EasyOCR reader inside the endpoint to save RAM
        reader = easyocr.Reader(['en'])
        result = process_lab_report(temp_file_path, reader)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        os.remove(temp_file_path)

    return result
