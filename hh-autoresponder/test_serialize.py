import json

width = 13
date_str = "2026-09-25 17:49"
url = "https://hh.ru/vacancy/135243260"
title = "Инженер данных"
company = "Test"
platform = "hh"
cover_letter = ""
status = "Ждем ответа"
score_str = "AI Score: 60"
vac_id = "135243260"
salary = ""

row_data = [""] * width
row_data[0] = date_str
row_data[1] = url
row_data[2] = title
row_data[3] = company
row_data[4] = ""
row_data[5] = f"Автоотклик ({platform or 'hh'})"
row_data[6] = cover_letter
row_data[7] = status
row_data[8] = score_str
row_data[9] = vac_id
row_data[10] = platform
row_data[11] = salary

try:
    json.dumps(row_data)
    print("Success")
except Exception as e:
    print(f"Error: {e}")
