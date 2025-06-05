from fastapi import FastAPI, File, UploadFile, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import pandas as pd
import msoffcrypto
import io

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def form_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

@app.post("/upload")
async def upload_excel(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()

        # 비밀번호 해제
        decrypted = io.BytesIO()
        office_file = msoffcrypto.OfficeFile(io.BytesIO(file_bytes))
        office_file.load_key(password="Bz6206")
        office_file.decrypt(decrypted)
        decrypted.seek(0)

        # Excel 읽기
        df = pd.read_excel(decrypted, engine="openpyxl")

        # 컬럼 체크
        if not {'라이더명', '배달처리비', '운행일'}.issubset(df.columns):
            return JSONResponse(status_code=400, content={"status": "error", "message": "데이터가 일치하지 않습니다."})

        # 문자열로 날짜 변환 (프론트 출력에 적합하게)
        df['운행일'] = df['운행일'].astype(str)

        result = {}

        grouped = df.groupby(['라이더명', '운행일'])['배달처리비'].sum().reset_index()

        for _, row in grouped.iterrows():
            rider = row['라이더명']
            if rider not in result:
                result[rider] = {
                    "총합계": 0,
                    "기록": []
                }
            result[rider]["기록"].append({
                "운행일": row["운행일"],
                "배달처리비": int(row["배달처리비"])
            })
            result[rider]["총합계"] += int(row["배달처리비"])

        return {
            "status": "success",
            "data": result
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

