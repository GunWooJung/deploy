import pymysql
from fastapi import FastAPI, File, UploadFile, Request, Form, Query, Path, Body
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import pandas as pd
import msoffcrypto
import io

from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from starlette.responses import RedirectResponse

app = FastAPI()
templates = Jinja2Templates(directory="templates")
# DB 연결 함수


def get_conn():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="djsqnr20214",
        database="test2",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )


@app.get("/")
def admin_redirect():
    return RedirectResponse(url="/admin-manage")


@app.get("/admin-manage", response_class=HTMLResponse)
def admin_member(request: Request):
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "data": []
    })


@app.get("/admin-member", response_class=HTMLResponse)
def admin_manage(request: Request):
    conn = get_conn()
    members = []
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, name, moto_fee FROM test2.member")
        results = cursor.fetchall()
        for row in results:
            members.append({
                "id": row["id"],
                "name": row["name"],
                "moto_fee": row["moto_fee"]
            })
    conn.close()

    return templates.TemplateResponse("member.html", {
        "request": request,
        "members": members
    })
# 회원 추가
@app.get("/member/add")
def add_member(name: str = Query(..., min_length=1)):

    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO member (name) VALUES (%s)", (name,))
        conn.commit()
    conn.close()
    return {"result": "ok"}


class MemberEdit(BaseModel):
    name: str
    moto_fee: int
    # 필요한 다른 필드들도 추가 가능


@app.put("/member/edit/{mid}")
def edit_member(
    mid: int = Path(...),
    data: MemberEdit = Body(...)
):
    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE test2.member SET moto_fee = %s WHERE id = %s and name = %s",
            (data.moto_fee, mid, data.name)
        )
        conn.commit()
    conn.close()
    return {"result": "ok"}


@app.get("/admin-manage", response_class=HTMLResponse)
async def form_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


async def fetch_moto_fees():
    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute("SELECT name, moto_fee FROM test2.member")
        result = cursor.fetchall()
    conn.close()
    return result  # {라이더명: moto_fee}


@app.post("/upload")
async def upload_excel(file1: UploadFile = File(...), file2: UploadFile = File(...)):
    try:

        # file1 처리 (기존)
        file_bytes = await file1.read()
        decrypted = io.BytesIO()
        office_file = msoffcrypto.OfficeFile(io.BytesIO(file_bytes))
        office_file.load_key(password="Bz6206")
        office_file.decrypt(decrypted)
        decrypted.seek(0)
        df = pd.read_excel(decrypted, engine="openpyxl")

        if not {'라이더명', '배달처리비', '운행일'}.issubset(df.columns):
            return JSONResponse(status_code=400, content={"status": "error", "message": "file 데이터가 일치하지 않습니다."})
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

        # file2 처리 (운행일, 이름, 보험료 발생금액(원))
        file2_bytes = await file2.read()
        decrypted2 = io.BytesIO()
        office_file2 = msoffcrypto.OfficeFile(io.BytesIO(file2_bytes))
        office_file2.load_key(password="Bz6206!6206")
        office_file2.decrypt(decrypted2)
        decrypted2.seek(0)
        df2 = pd.read_excel(decrypted2, engine="openpyxl")

        if not {'운행일', '이름', '보험료 발생금액(원)'}.issubset(df2.columns):
            return JSONResponse(status_code=400, content={"status": "error", "message": "file2 데이터가 일치하지 않습니다."})
        df2['운행일'] = df2['운행일'].astype(str)

        insurance_data = df2.groupby(['이름', '운행일'])['보험료 발생금액(원)'].sum().reset_index()
        insurance_dict = {}
        for _, row in insurance_data.iterrows():
            rider = row['이름']
            운행일 = row['운행일']
            insurance_fee = int(row['보험료 발생금액(원)'])

            if rider not in insurance_dict:
                insurance_dict[rider] = {}
            insurance_dict[rider][운행일] = insurance_fee

        # 기존 result에 보험료 발생금액(원) 추가 + 보험료만 있는 데이터도 포함
        for rider, 운행일_dict in insurance_dict.items():
            if rider not in result:
                result[rider] = {
                    "총합계": 0,
                    "기록": []
                }

            # 보험료 있는 운행일마다 기록 존재하는지 확인 후 없으면 새로 추가
            for 운행일, 보험료 in 운행일_dict.items():
                # 기록 중 운행일 있는지 찾기
                records = result[rider]["기록"]
                rec = next((r for r in records if r["운행일"] == 운행일), None)
                if rec:
                    rec["보험료 발생금액(원)"] = 보험료
                else:
                    # 배달처리비는 없으니 0으로 넣기
                    result[rider]["기록"].append({
                        "운행일": 운행일,
                        "배달처리비": 0,
                        "보험료 발생금액(원)": 보험료
                    })

            # 일 오토바이
        moto_fee_list = await fetch_moto_fees()

        # 리스트 → 딕셔너리로 변환: {'정건우': 13000, ...}
        moto_fee_map = {entry['name']: entry['moto_fee'] for entry in moto_fee_list}

        for rider in result:
            result[rider]["moto_fee"] = moto_fee_map.get(rider, 0)

        return {
            "status": "success",
            "data": result
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
