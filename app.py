import cv2
import easyocr
import re
import numpy as np
import shutil
import os
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

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
            lower, upper = map(lambda x: float(x.strip().replace(',', '.')), reference_range.split('-'))
            return value < lower or value > upper
        return False
    except Exception:
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
            for match in re.finditer(pattern, line):
                groups = match.groups()
                test_name = groups[0].strip()
                test_value = groups[1].strip()
                test_unit = groups[2].strip() if len(groups) > 2 and groups[2] else ""
                ref_range = groups[3].strip().replace(' ', '') if len(groups) > 3 else groups[2].strip().replace(' ', '')

                lab_tests.append({
                    "test_name": test_name,
                    "test_value": test_value,
                    "bio_reference_range": ref_range,
                    "test_unit": test_unit,
                    "lab_test_out_of_range": check_if_out_of_range(test_value, ref_range)
                })

    return lab_tests if lab_tests else extract_using_specialized_patterns(text, lines)

def extract_using_specialized_patterns(text, lines):
    lab_tests = []
    test_name_pattern = r'([A-Z][A-Za-z\s\(\)]{2,})'
    value_pattern = r'([0-9\.,]+)\s*([a-zA-Z%/]+)?'
    range_pattern = r'([0-9\.,]+\s*-\s*[0-9\.,]+)'

    for i, line in enumerate(lines):
        for test_match in re.finditer(test_name_pattern, line):
            test_name = test_match.group(1).strip()
            if test_name.lower() in ['test', 'name', 'value', 'range', 'result', 'parameter']:
                continue

            remainder = line[test_match.end():]
            test_value = test_unit = ref_range = ""

            match_value = re.search(value_pattern, remainder)
            match_range = re.search(range_pattern, remainder)

            if match_value:
                test_value = match_value.group(1).strip()
                test_unit = match_value.group(2).strip() if match_value.group(2) else ""
                if match_range:
                    ref_range = match_range.group(1).strip()
            elif i + 1 < len(lines):
                next_line = lines[i + 1]
                match_value = re.search(value_pattern, next_line)
                match_range = re.search(range_pattern, next_line)
                if match_value:
                    test_value = match_value.group(1).strip()
                    test_unit = match_value.group(2).strip() if match_value.group(2) else ""
                if match_range:
                    ref_range = match_range.group(1).strip()

            if test_value:
                ref_range = ref_range.replace(' ', '')
                lab_tests.append({
                    "test_name": test_name,
                    "test_value": test_value,
                    "bio_reference_range": ref_range,
                    "test_unit": test_unit,
                    "lab_test_out_of_range": check_if_out_of_range(test_value, ref_range)
                })

    return lab_tests

def process_lab_report(image_path):
    reader = easyocr.Reader(['en'], gpu=False)
    full_text, full_text_lower, lines = extract_clean_text(image_path, reader)
    lab_tests = extract_lab_tests(full_text, full_text_lower, lines)
    return {"is_success": bool(lab_tests), "data": lab_tests}

@app.post("/get-lab-tests")
async def get_lab_tests(file: UploadFile = File(...)):
    temp_dir = "/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, file.filename)

    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        result = process_lab_report(temp_path)
        return JSONResponse(status_code=200, content=result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        os.remove(temp_path)
