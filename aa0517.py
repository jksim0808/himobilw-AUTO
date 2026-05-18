import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
from datetime import datetime

# --- 1. 한국투자증권 API 통신 클래스 ---
class KoreaInvestmentAPI:
    def __init__(self, app_key, app_secret, mock_flag=True):
        # mock_flag가 True이면 모의투자 서버, False이면 실운영 서버 주소 세팅
        if mock_flag:
            self.base_url = "https://openapivts.koreainvestment.com:29443" # 모의투자
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"    # 실운영
            
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = None

    def get_access_token(self):
        """OAuth2.0 접근 토큰(Access Token) 발급"""
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                self.access_token = response.json().get("access_token")
                return True
            else:
                st.sidebar.error(f"토큰 발급 실패: {response.json().get('error_description')}")
                return False
        except Exception as e:
            st.sidebar.error(f"한투 서버 연결 실패: {e}")
            return False

    def get_realtime_price(self, ticker):
        """주식현재가 일자별/시간별 체결 데이터 조회 (TR: FHKST01010100)"""
        if not self.access_token:
            if not self.get_access_token():
                return None

        url = f"{self.base_url}/uapi/domestic-stock/v1/quoting/inquire-price"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100"  # 주식현재가 기본 조회 TR ID
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",  # 주식 종목 분류 (J: 주식)
            "FID_INPUT_ISCD": ticker       # 종목코드 6자리
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                res_data = response.json().get("output", {})
                
                # 한투 API 명세서 규격 데이터 파싱 (stck_prpr: 현재가, stck_hgpr: 고가, stck_lwpr: 저가, accl_tr_vol: 누적거래량)
                return {
                    "Close": float(res_data.get("stck_prpr", 0)),
                    "High": float(res_data.get("stck_hgpr", 0)),
                    "Low": float(res_data.get("stck_lwpr", 0)),
                    "Volume": float(res_data.get("accl_tr_vol", 0))
                }
            else:
                st.error(f"시세 조회 오류: {response.text}")
                return None
        except Exception as e:
            st.error(f"API 통신 오류: {e}")
            return None

# --- 2. 퀀트 단타 지표 연산 알고리즘 ---
def calculate_indicators(df):
    if len(df) < 2:
        return df
        
    # VWAP (거래량 가중 평균선) 계산
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    df['Price_Vol'] = typical_price * df['Volume']
    df['VWAP'] = df['Price_Vol'].cumsum() / (df['Volume'].cumsum() + 1e-9)
    
    # 단기 RSI 계산
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=min(5, len(df)-1), min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=min(5, len(df)-1), min_periods=1).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    
    # 단기 전고점 저항선 및 거래량 이평선
    df['Local_High'] = df['High'].shift(1).rolling(window=min(3, len(df)-1), min_periods=1).max()
    df['Vol_MA'] = df['Volume'].shift(1).rolling(window=min(3, len(df)-1), min_periods=1).mean()
    return df

# --- 3. 웹 UI 화면 구성 ---
st.set_page_config(page_title="한투 API 실시간 단타기", layout="wide")

st.title("🏹 한국투자증권 Open API 실시간 단타 예측 대시보드")
st.markdown("한국투자증권 오픈 API와 직접 통신하여 실제 장중 수급 데이터와 알고리즘 타점을 매칭합니다.")

# 세션 상태(Session State)를 활용해 실시간으로 받아오는 데이터를 누적 적층
if "stock_history" not in st.session_state:
    st.session_state.stock_history = pd.DataFrame()
if "last_ticker" not in st.session_state:
    st.session_state.last_ticker = ""

# 사이드바 설정 (보안 입력 적용)
st.sidebar.header("🔑 한투 Open API 인증 정보")
app_key = st.sidebar.text_input("App Key", type="password")
app_secret = st.sidebar.text_input("App Secret", type="password")
server_type = st.sidebar.radio("서버 선택", ["모의투자 서버", "실운영 서버"])
mock_flag = True if server_type == "모의투자 서버" else False

st.sidebar.markdown("---")
st.sidebar.header("🔍 종목 설정")
ticker_input = st.sidebar.text_input("종목코드 입력 (6자리 + Enter)", value="005930")

# 종목이 바뀌면 기존 누적 히스토리 초기화
if ticker_input != st.session_state.last_ticker:
    st.session_state.stock_history = pd.DataFrame()
    st.session_state.last_ticker = ticker_input

if st.sidebar.button("🔄 실시간 시세 갱신 및 타점 연산"):
    if app_key and app_secret:
        api = KoreaInvestmentAPI(app_key, app_secret, mock_flag=mock_flag)
        tick_data = api.get_realtime_price(ticker_input)
        
        if tick_data and tick_data["Close"] > 0:
            # 새로운 틱 데이터를 데이터프레임 행으로 생성
            new_row = pd.DataFrame([{
                "Close": tick_data["Close"],
                "High": tick_data["High"],
                "Low": tick_data["Low"],
                "Volume": tick_data["Volume"]
            }], index=[pd.to_datetime(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))])
            
            # 최신 30개의 체결 데이터 누적 유지
            st.session_state.stock_history = pd.concat([st.session_state.stock_history, new_row]).tail(30)
            
            # 단타 지표 연산 적용
            df = calculate_indicators(st.session_state.stock_history.copy())
            latest = df.iloc[-1]
            prev_close = df['Close'].iloc[-2] if len(df) > 1 else latest['Close']
            prev_local_high = latest['Local_High'] if not pd.isna(latest['Local_High']) else latest['Close']
            prev_vol_ma = latest['Vol_MA'] if not pd.isna(latest['Vol_MA']) else latest['Volume']
            
            # --- 단타 돌파구간 매수 조건문 ---
            cond_breakout = latest['Close'] >= prev_local_high
            st_above_vwap = latest['Close'] > latest['VWAP']
            cond_volume = latest['Volume'] > (prev_vol_ma * 1.05) # 한투 누적 거래량 증가율 매칭
            
            is_buy_signal = cond_breakout and st_above_vwap and cond_volume
            
            # --- 상단 실시간 스코어보드 ---
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric(label=f"현재 체결가", value=f"{int(latest['Close']):,} 원", delta=f"{int(latest['Close'] - prev_close):,} 원")
            with col2:
                st.metric(label="당일 누적 거래량", value=f"{int(latest['Volume']):,} 주")
            with col3:
                st.metric(label="단기 저항선 (직전고가)", value=f"{int(prev_local_high):,} 원")
            with col4:
                st.metric(label="RSI (단기 심리지표)", value=f"{int(latest['RSI'])}" if not pd.isna(latest['RSI']) else "계산중")
                
            st.markdown("---")
            
            # 타점 포착 알림 스크린
            if is_buy_signal:
                st.error(f"🔥 [한투 API 매수 타점] {ticker_input} 종목이 저항선을 돌파하고 당일 거래량 가중 평균선(VWAP) 상방에 안착했습니다!")
                st.balloons()
            else:
                st.success(f"🟢 [한투 API 정상 연동] 현재 {ticker_input} 종목 실시간 추적 중. 특이 수급 대기 상태.")
                
            # 수급 및 주가 차트 시각화
            st.subheader("📊 주가 및 단기 수급선(VWAP) 추이 분석")
            chart_data = df[['Close', 'VWAP']]
            chart_data.columns = ['현재가', '수급평균선(VWAP)']
            st.line_chart(chart_data)
            
            # 상세 테이블 리포트
            st.dataframe(df.tail(5)[['Close', 'Volume', 'VWAP', 'RSI']], use_container_width=True)
            st.caption(f"최종 데이터 동기화 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        st.sidebar.warning("⚠️ App Key와 App Secret을 입력한 후 갱신 버튼을 눌러주세요.")
else:
    st.info("💡 왼쪽 사이드바에 한국투자증권 API Key 정보를 입력하고 [실시간 시세 갱신] 버튼을 누르면 정식 연동이 시작됩니다.")
