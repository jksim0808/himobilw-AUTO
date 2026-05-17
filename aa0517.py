import streamlit as st
import pandas as pd
import numpy as np
import requests
import xml.etree.ElementTree as ET
import time
import re
import plotly.graph_objects as god
from plotly.subplots import make_subplots

st.set_page_config(page_title="하이모바일 주식 매니저 (AI 완벽보정형)", layout="wide")

st.title("🤖 하이모바일 AI 결합 주식 스크리닝 매니저")
st.caption("Gemini AI 종목 추천 + 데이터 누락 방지 초강력 파싱 시스템")

# ==========================================
# 🔑 Gemini API 설정
# ==========================================
GEMINI_API_KEY = "YOUR_API_KEY_HERE"  # <-- 실제 API 키를 입력하세요.

DEFAULT_STOCKS_TEXT = (
    "삼성전자:005930, SK하이닉스:000660, 한미반도체:042700, 리노공업:058470, "
    "현대차:005380, 기아:000270, 현대로템:064350, 한화에어로스페이스:012450"
)

if 'selected_stock_code' not in st.session_state:
    st.session_state.selected_stock_code = None
if 'selected_stock_name' not in st.session_state:
    st.session_state.selected_stock_name = None
if 'screening_results' not in st.session_state:
    st.session_state.screening_results = {"success": [], "warning": [], "info": []}
if 'ai_stocks_text' not in st.session_state:
    st.session_state.ai_stocks_text = DEFAULT_STOCKS_TEXT

def get_gemini_recommended_stocks():
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_API_KEY_HERE":
        return (
            "삼성전자:005930, SK하이닉스:000660, 한미반도체:042700, 리노공업:058470, 이오테크닉스:039030, "
            "HPSP:403870, 가온칩스:454840, 오픈에지테크놀로지:394280, 에이직랜드:445090, 주성엔지니어링:036930, "
            "현대차:005380, 기아:000270, 현대로템:064350, 현대모비스:012330, HL만도:204320, "
            "HD현대인프라코어:042670, 한국항공우주:047810, 한화에어로스페이스:012450, LIG넥스원:079550, 두산로보틱스:454910, "
            "레인보우로보틱스:277810, 뉴로메카:348340, LG에너지솔루션:373220, 삼성SDI:006400, 포스코퓨처엠:003670, "
            "에코프로비엠:247540, 엘앤에프:066970, HD현대일렉트릭:043200, 효성중공업:298040, LS일렉트릭:010120, "
            "두산에너빌리티:034020, 한화솔루션:009830, 씨에스윈드:112610, 삼성바이오로직스:207940, 셀트리온:068270, "
            "유한양행:000100, 알테오জেন:196170, 리그켐바이오:141080, 에이비엘바이오:298380, 휴젤:145020, "
            "메디톡스:086900, 한미약품:128940, SK바이오팜:326030, KB금융:105560, 신한지주:055550, "
            "하나금융지주:086790, 메리츠금융지주:138040, 삼성물산:028260, SK:034730, POSCO홀딩스:005490"
        )
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        prompt = (
            "대한민국 주식 시장에서 유망한 종목 50개를 선정해줘. "
            "출력 형식은 반드시 '종목명:6자리코드' 형태로 콤마로 연결해줘. 다른 미사여구나 마크다운 기호(**, ` 등)는 절대 붙이지마. "
            "예시: 삼성전자:005930, SK하이닉스:000660"
        )
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(url, headers=headers, json=data, timeout=5)
        text_result = response.json()['candidates'][0]['content']['parts'][0]['text']
        return text_result.strip()
    except Exception:
        return DEFAULT_STOCKS_TEXT

def get_mobile_naver_data(code, count=100):
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1',
            'Referer': f'https://m.stock.naver.com/domestic/stock/{code}/total'
        }
        response = requests.get(url, headers=headers, timeout=3)
        root = ET.fromstring(response.text)
        parsed_data = []
        for item in root.findall('.//item'):
            data_row = item.get('data').split('|')
            parsed_data.append(data_row)
        if not parsed_data: return pd.DataFrame()
        df = pd.DataFrame(parsed_data, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Date'] = pd.to_datetime(df['Date'], format='%Y%m%d').dt.strftime('%Y-%m-%d')
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except Exception:
        return pd.DataFrame()

def calculate_rsi(series, period=14):
    delta = series.diff()
    up, down = delta.clip(lower=0), -delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    return 100 - (100 / (1 + (ema_up / ema_down)))

st.markdown("### 📊 시스템 3단계 복합 판단 로직 설계서")
lead_col1, lead_col2, lead_col3 = st.columns(3)
with lead_col1:
    st.markdown("<div style='background-color:#e8f5e9; padding:12px; border-radius:10px; border-left:5px solid #2e7d32;'><b>📈 1단계: 매수 긍정</b><br><span style='font-size:12px;'>정배열 + RSI 안전대(45~65) + 거래량 활성화(Brief)</span></div>", unsafe_allow_html=True)
with lead_col2:
    st.markdown("<div style='background-color:#fffde7; padding:12px; border-radius:10px; border-left:5px solid #fbc02d;'><b>⚠️ 2단계: 진입 조율 필요</b><br><span style='font-size:12px;'>정배열이나 단기 과열(RSI>65) 또는 거래량 부족</span></div>", unsafe_allow_html=True)
with lead_col3:
    st.markdown("<div style='background-color:#efebe9; padding:12px; border-radius:10px; border-left:5px solid #4e342e;'><b>💤 3단계: 관망 권장</b><br><span style='font-size:12px;'>이평선 역배열 또는 20일선 붕괴 리스크 구역</span></div>", unsafe_allow_html=True)

st.markdown("---")

st.markdown("### 🛠️ 종목 리스트 제어 센터")
ai_col1, ai_col2 = st.columns([0.3, 0.7])

with ai_col1:
    st.write("")
    if st.button("🪄 Gemini AI 유망 종목 50개 자동 추출", use_container_width=True, type="primary"):
        with st.spinner("Gemini가 유망 섹터 우량주 50개를 엄선하는 중..."):
            recommended_text = get_gemini_recommended_stocks()
            st.session_state.ai_stocks_text = recommended_text
            st.success("🤖 AI 추천 리스트가 하단에 주입되었습니다!")

with ai_col2:
    user_stocks_input = st.text_area("현재 분석 대상 종목 필드", value=st.session_state.ai_stocks_text, height=70, key="raw_input_area")

# ==========================================
# ⚠️ 초강력 보정 정규식 파싱 엔진 (오류 해결 핵심)
# ==========================================
current_stocks_map = {}
# 콤마, 줄바꿈, 공백, 따옴표 등을 기준으로 유연하게 쪼갭니다.
raw_items = re.split(r'[,\n\t\"\'\`]', user_stocks_input)
for item in raw_items:
    if ":" in item:
        name_part, code_part = item.split(":", 1)
        # 한글/영어/숫자만 이름으로 인정 (특수문자 제거)
        clean_name = re.sub(r'[^a-zA-Z0-9가-힣]', '', name_part).strip()
        # 코드 파트에서는 오직 '숫자'만 추출한 뒤 6자리로 강제 포맷팅
        clean_code = ''.join(filter(str.isdigit, code_part)).strip()
        
        if clean_name and len(clean_code) >= 6:
            # 혹시 6자리가 넘어가거나 하면 앞의 6자리만 커트
            clean_code = clean_code[:6]
            current_stocks_map[clean_name] = clean_code

st.info(f"📋 안전하게 파싱된 분석 대기 종목: 총 **{len(current_stocks_map)}**개")

# ==========================================
# 전수 스크리닝 실행
# ==========================================
if st.button("🚀 실시간 보정형 전수 분석 및 3단계 스크리닝 시작", use_container_width=True):
    success_list, warning_list, info_list = [], [], []
    
    if not current_stocks_map:
        st.error("파싱된 종목이 없습니다. 텍스트 형식을 확인해 주세요. (예: 삼성전자:005930)")
    else:
        progress_bar = st.progress(0)
        total_stocks = len(current_stocks_map)
        
        for idx, (name, code) in enumerate(current_stocks_map.items()):
            progress_bar.progress((idx + 1) / total_stocks)
            df = get_mobile_naver_data(code)
            
            if not df.empty and len(df) >= 60: # 최소 60일치 데이터 확보 시에만 이평선 계산
                df['MA20'] = df['Close'].rolling(window=20).mean()
                df['MA60'] = df['Close'].rolling(window=60).mean()
                df['RSI'] = calculate_rsi(df['Close'])
                df['Vol_MA5'] = df['Volume'].shift(1).rolling(window=5).mean()
                
                curr_price = int(df['Close'].iloc[-1])
                curr_rsi = float(df['RSI'].iloc[-1]) if not pd.isna(df['RSI'].iloc[-1]) else 50.0
                ma20 = float(df['MA20'].iloc[-1]) if not pd.isna(df['MA20'].iloc[-1]) else 0.0
                ma60 = float(df['MA60'].iloc[-1]) if not pd.isna(df['MA60'].iloc[-1]) else 0.0
                curr_vol = float(df['Volume'].iloc[-1])
                vol_ma5 = float(df['Vol_MA5'].iloc[-1]) if not pd.isna(df['Vol_MA5'].iloc[-1]) else 0.0
                
                vol_ratio = curr_vol / vol_ma5 if vol_ma5 > 0 else 0.0
                
                stock_info = {
                    "종목명": name, "종목코드": code, "현재가": f"{curr_price:,}원",
                    "RSI": round(curr_rsi, 1), "거래량비율": f"{vol_ratio * 100:.1f}%"
                }
                
                if curr_price > ma20 > ma60 and 45 <= curr_rsi <= 65 and vol_ratio >= 0.9:
                    success_list.append(stock_info)
                elif curr_price > ma20 > ma60:
                    warning_list.append(stock_info)
                else:
                    info_list.append(stock_info)
            else:
                # 데이터 수집 실패 시 관망 리스트에 임시 주입 (코드 불량 확인용)
                info_list.append({"종목명": name, "종목코드": code, "현재가": "데이터 오류", "RSI": 0, "거래량비율": "0%"})
            time.sleep(0.04)
            
        progress_bar.empty()
        st.session_state.screening_results = {"success": success_list, "warning": warning_list, "info": info_list}

# ==========================================
# 결과 출력 창
# ==========================================
col1, col2, col3 = st.columns(3)
with col1:
    st.success(f"📈 매수 긍정 ({len(st.session_state.screening_results['success'])}개)")
    if st.session_state.screening_results['success']:
        df_suc = pd.DataFrame(st.session_state.screening_results['success'])
        sel_suc = st.dataframe(df_suc, use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun")
        if sel_suc.selection.rows:
            st.session_state.selected_stock_name = df_suc.iloc[sel_suc.selection.rows[0]]['종목명']
            st.session_state.selected_stock_code = df_suc.iloc[sel_suc.selection.rows[0]]['종목코드']

with col2:
    st.warning(f"⚠️ 진입 조율 필요 ({len(st.session_state.screening_results['warning'])}개)")
    if st.session_state.screening_results['warning']:
        df_war = pd.DataFrame(st.session_state.screening_results['warning'])
        sel_war = st.dataframe(df_war, use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun")
        if sel_war.selection.rows:
            st.session_state.selected_stock_name = df_war.iloc[sel_war.selection.rows[0]]['종목명']
            st.session_state.selected_stock_code = df_war.iloc[sel_war.selection.rows[0]]['종목코드']

with col3:
    st.info(f"💤 관망 권장 ({len(st.session_state.screening_results['info'])}개)")
    if st.session_state.screening_results['info']:
        df_inf = pd.DataFrame(st.session_state.screening_results['info'])
        sel_inf = st.dataframe(df_inf, use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun")
        if sel_inf.selection.rows:
            st.session_state.selected_stock_name = df_inf.iloc[sel_inf.selection.rows[0]]['종목명']
            st.session_state.selected_stock_code = df_inf.iloc[sel_inf.selection.rows[0]]['종목코드']

# 차트 시각화
if st.session_state.selected_stock_code:
    st.markdown("---")
    name = st.session_state.selected_stock_name
    code = st.session_state.selected_stock_code
    
    c_left, c_right = st.columns([0.85, 0.15])
    with c_left:
        st.subheader(f"📊 현재 선택된 차트: {name} ({code})")
    with c_right:
        if st.button("❌ 차트 닫기", use_container_width=True):
            st.session_state.selected_stock_code = None
            st.session_state.selected_stock_name = None
            st.rerun()
            
    if st.session_state.selected_stock_code:
        df_chart = get_mobile_naver_data(code, count=100)
        if not df_chart.empty:
            df_chart['MA20'] = df_chart['Close'].rolling(window=20).mean()
            df_chart['MA60'] = df_chart['Close'].rolling(window=60).mean()
            df_chart['RSI'] = calculate_rsi(df_chart['Close'])

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
            fig.add_trace(god.Candlestick(
                x=df_chart['Date'], open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'],
                name='주가', increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
            ), row=1, col=1)

            fig.add_trace(god.Scatter(x=df_chart['Date'], y=df_chart['MA20'], line=dict(color='#ff9800', width=1.5), name='20일선'), row=1, col=1)
            fig.add_trace(god.Scatter(x=df_chart['Date'], y=df_chart['MA60'], line=dict(color='#2196f3', width=1.5), name='60일선'), row=1, col=1)
            fig.add_trace(god.Scatter(x=df_chart['Date'], y=df_chart['RSI'], line=dict(color='#9c27b0', width=1.5), name='RSI'), row=2, col=1)
            
            fig.add_hline(y=65, line_dash="dash", line_color="red", line_width=1, row=2, col=1)
            fig.add_hline(y=45, line_dash="dash", line_color="blue", line_width=1, row=2, col=1)

            fig.update_layout(
                yaxis_title="주가 (원)", yaxis2_title="RSI",
                xaxis_rangeslider_visible=False, height=500,
                margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified"
            )
            fig.update_yaxes(range=[10, 90], row=2, col=1)
            st.plotly_chart(fig, use_container_width=True)
