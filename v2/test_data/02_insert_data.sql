-- ============================================
-- SQL Tuner v2 - 테스트 데이터 생성 (경량 버전)
-- 고객 1만 / 상품 1천 / 주문 10만 / 주문상세 30만
-- 예상 소요 시간: 1~3분
-- ============================================

-- 고객 데이터 (1만 건)
INSERT /*+ APPEND */ INTO TUNING_CUSTOMER
SELECT
    LEVEL AS CUSTOMER_ID,
    'CUSTOMER_' || LPAD(LEVEL, 6, '0') AS CUSTOMER_NAME,
    'user' || LEVEL || '@test.com' AS EMAIL,
    CASE MOD(LEVEL, 10)
        WHEN 0 THEN 'VIP'
        WHEN 1 THEN 'GOLD'
        ELSE 'NORMAL'
    END AS GRADE,
    SYSDATE - MOD(LEVEL * 7, 1825) AS JOIN_DATE,
    CASE MOD(LEVEL, 5)
        WHEN 0 THEN '서울'
        WHEN 1 THEN '경기'
        WHEN 2 THEN '부산'
        WHEN 3 THEN '대구'
        ELSE '기타'
    END AS REGION
FROM DUAL
CONNECT BY LEVEL <= 10000;
COMMIT;

-- 상품 데이터 (1천 건)
INSERT /*+ APPEND */ INTO TUNING_PRODUCT
SELECT
    LEVEL AS PRODUCT_ID,
    'PRODUCT_' || LPAD(LEVEL, 5, '0') AS PRODUCT_NAME,
    CASE MOD(LEVEL, 6)
        WHEN 0 THEN '전자제품'
        WHEN 1 THEN '의류'
        WHEN 2 THEN '식품'
        WHEN 3 THEN '가구'
        WHEN 4 THEN '도서'
        ELSE '기타'
    END AS CATEGORY,
    ROUND(1000 + (MOD(LEVEL * 317, 99000)), 2) AS PRICE,
    MOD(LEVEL * 13, 500) AS STOCK_QTY,
    SYSDATE - MOD(LEVEL * 3, 730) AS REG_DATE
FROM DUAL
CONNECT BY LEVEL <= 1000;
COMMIT;

-- 주문 데이터 (10만 건, 한 번에 insert)
INSERT /*+ APPEND */ INTO TUNING_ORDERS
SELECT
    LEVEL AS ORDER_ID,
    MOD(LEVEL * 11, 10000) + 1 AS CUSTOMER_ID,
    SYSDATE - MOD(LEVEL * 11, 730) AS ORDER_DATE,
    CASE MOD(LEVEL, 10)
        WHEN 0 THEN 'CANCEL'
        WHEN 1 THEN 'PENDING'
        ELSE 'COMPLETE'
    END AS STATUS,
    ROUND(10000 + MOD(LEVEL * 777, 990000), 2) AS TOTAL_AMOUNT,
    CASE MOD(LEVEL, 5)
        WHEN 0 THEN '서울'
        WHEN 1 THEN '경기'
        WHEN 2 THEN '부산'
        WHEN 3 THEN '대구'
        ELSE '기타'
    END AS SHIP_REGION
FROM DUAL
CONNECT BY LEVEL <= 100000;
COMMIT;

-- 주문상세 데이터 (30만 건, 3회 분할)
DECLARE
    v_start NUMBER;
BEGIN
    FOR i IN 1..3 LOOP
        v_start := (i - 1) * 100000 + 1;
        INSERT /*+ APPEND */ INTO TUNING_ORDER_ITEM
        SELECT
            LEVEL + v_start - 1 AS ITEM_ID,
            MOD(LEVEL + v_start, 100000) + 1 AS ORDER_ID,
            MOD(LEVEL + v_start * 7, 1000) + 1 AS PRODUCT_ID,
            MOD(LEVEL, 9) + 1 AS QTY,
            ROUND(1000 + MOD((LEVEL + v_start) * 317, 99000), 2) AS UNIT_PRICE,
            ROUND(MOD(LEVEL, 30) * 0.01, 2) AS DISCOUNT
        FROM DUAL
        CONNECT BY LEVEL <= 100000;
        COMMIT;
    END LOOP;
END;
/