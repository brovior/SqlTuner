-- ============================================
-- SQL Tuner v2 - 튜닝 테스트 쿼리 모음 (업그레이드)
-- 테이블: TUNING_CUSTOMER / TUNING_PRODUCT
--         TUNING_ORDERS / TUNING_ORDER_ITEM
-- ============================================

-- ────────────────────────────────────────────
-- [FTS-01] Full Table Scan - STATUS 인덱스 없음
-- ────────────────────────────────────────────
SELECT * FROM TUNING_ORDERS
WHERE STATUS = 'CANCEL';

-- ────────────────────────────────────────────
-- [FTS-02] 함수로 인덱스 무력화
-- 튜닝: ORDER_DATE >= TO_DATE('2024-01-01') 방식으로 변경
-- ────────────────────────────────────────────
SELECT * FROM TUNING_ORDERS
WHERE TO_CHAR(ORDER_DATE, 'YYYY') = '2024';

-- ────────────────────────────────────────────
-- [FTS-03] LIKE 앞자리 와일드카드 - 인덱스 무력화
-- ────────────────────────────────────────────
SELECT * FROM TUNING_CUSTOMER
WHERE CUSTOMER_NAME LIKE '%김%';

-- ────────────────────────────────────────────
-- [FTS-04] TOTAL_AMOUNT 범위 조건 - 인덱스 없음
-- ────────────────────────────────────────────
SELECT ORDER_ID, CUSTOMER_ID, TOTAL_AMOUNT
FROM TUNING_ORDERS
WHERE TOTAL_AMOUNT BETWEEN 100000 AND 500000
AND STATUS = 'COMPLETE';

-- ────────────────────────────────────────────
-- [JOIN-01] Cartesian Join - 조인 조건 누락
-- ────────────────────────────────────────────
SELECT C.CUSTOMER_NAME, O.ORDER_ID
FROM TUNING_CUSTOMER C, TUNING_ORDERS O
WHERE C.REGION = '서울';

-- ────────────────────────────────────────────
-- [JOIN-02] 4테이블 조인 + 인덱스 없는 컬럼 조건
-- 비효율적인 조인 순서 + PRODUCT_ID 인덱스 없음
-- ────────────────────────────────────────────
SELECT
    C.CUSTOMER_NAME,
    C.GRADE,
    O.ORDER_DATE,
    O.STATUS,
    P.PRODUCT_NAME,
    P.CATEGORY,
    I.QTY,
    I.UNIT_PRICE,
    I.QTY * I.UNIT_PRICE * (1 - NVL(I.DISCOUNT,0)/100) AS NET_AMOUNT
FROM TUNING_ORDERS O,
     TUNING_CUSTOMER C,
     TUNING_ORDER_ITEM I,
     TUNING_PRODUCT P
WHERE O.CUSTOMER_ID = C.CUSTOMER_ID
AND   I.ORDER_ID    = O.ORDER_ID
AND   P.PRODUCT_ID  = I.PRODUCT_ID
AND   O.STATUS      = 'COMPLETE'
AND   P.CATEGORY    = 'ELECTRONICS'
AND   C.GRADE       IN ('VIP', 'GOLD')
ORDER BY O.ORDER_DATE DESC;

-- ────────────────────────────────────────────
-- [SUB-01] NOT IN 서브쿼리 - NULL 처리 위험
-- ────────────────────────────────────────────
SELECT * FROM TUNING_CUSTOMER
WHERE CUSTOMER_ID NOT IN (
    SELECT CUSTOMER_ID FROM TUNING_ORDERS
    WHERE STATUS = 'COMPLETE'
);

-- ────────────────────────────────────────────
-- [SUB-02] 스칼라 서브쿼리 - 행마다 반복 실행
-- ────────────────────────────────────────────
SELECT
    O.ORDER_ID,
    O.TOTAL_AMOUNT,
    (SELECT C.CUSTOMER_NAME FROM TUNING_CUSTOMER C
     WHERE C.CUSTOMER_ID = O.CUSTOMER_ID) AS CUST_NAME,
    (SELECT COUNT(*) FROM TUNING_ORDER_ITEM I
     WHERE I.ORDER_ID = O.ORDER_ID) AS ITEM_CNT
FROM TUNING_ORDERS O
WHERE O.ORDER_DATE >= SYSDATE - 30;

-- ────────────────────────────────────────────
-- [SUB-03] 중첩 서브쿼리 3단계 - 실행계획 복잡도 상승
-- 고객별 최대 주문금액의 80% 이상 주문 조회
-- ────────────────────────────────────────────
SELECT O.ORDER_ID, O.CUSTOMER_ID, O.TOTAL_AMOUNT
FROM TUNING_ORDERS O
WHERE O.TOTAL_AMOUNT >= (
    SELECT MAX(O2.TOTAL_AMOUNT) * 0.8
    FROM TUNING_ORDERS O2
    WHERE O2.CUSTOMER_ID = O.CUSTOMER_ID
    AND O2.STATUS = 'COMPLETE'
)
AND O.STATUS = 'COMPLETE'
AND O.CUSTOMER_ID IN (
    SELECT CUSTOMER_ID FROM TUNING_CUSTOMER
    WHERE GRADE = 'VIP'
);

-- ────────────────────────────────────────────
-- [PAGE-01] 잘못된 페이징 - ORDER BY 없는 ROWNUM
-- ────────────────────────────────────────────
SELECT * FROM (
    SELECT * FROM TUNING_ORDERS
    ORDER BY ORDER_DATE DESC
) WHERE ROWNUM <= 20;

-- ────────────────────────────────────────────
-- [PAGE-02] 중간 페이지 페이징 - 이중 ROWNUM 안티패턴
-- 튜닝: ROW_NUMBER() OVER() 방식 권장
-- ────────────────────────────────────────────
SELECT * FROM (
    SELECT ROWNUM AS RN, A.*
    FROM (
        SELECT O.ORDER_ID, O.ORDER_DATE, O.TOTAL_AMOUNT,
               C.CUSTOMER_NAME
        FROM TUNING_ORDERS O
        JOIN TUNING_CUSTOMER C ON O.CUSTOMER_ID = C.CUSTOMER_ID
        WHERE O.STATUS = 'COMPLETE'
        ORDER BY O.ORDER_DATE DESC
    ) A
    WHERE ROWNUM <= 100
)
WHERE RN >= 81;

-- ────────────────────────────────────────────
-- [IDX-01] 묵시적 형변환으로 인덱스 무력화
-- CUSTOMER_ID는 NUMBER인데 문자열 비교
-- ────────────────────────────────────────────
SELECT * FROM TUNING_ORDERS
WHERE CUSTOMER_ID = '12345';

-- ────────────────────────────────────────────
-- [IDX-02] OR 조건으로 인덱스 분산 - FTS 유발 가능
-- ────────────────────────────────────────────
SELECT ORDER_ID, ORDER_DATE, STATUS
FROM TUNING_ORDERS
WHERE STATUS = 'PENDING'
OR STATUS = 'CANCEL'
OR TOTAL_AMOUNT > 1000000;

-- ────────────────────────────────────────────
-- [AGG-01] 불필요한 DISTINCT
-- ────────────────────────────────────────────
SELECT DISTINCT C.CUSTOMER_NAME
FROM TUNING_CUSTOMER C
JOIN TUNING_ORDERS O ON C.CUSTOMER_ID = O.CUSTOMER_ID
WHERE O.STATUS = 'COMPLETE';

-- ────────────────────────────────────────────
-- [AGG-02] GROUP BY + HAVING + 서브쿼리 복합
-- 월별 매출 상위 3개 카테고리
-- ────────────────────────────────────────────
SELECT
    TO_CHAR(O.ORDER_DATE, 'YYYY-MM') AS ORDER_MONTH,
    P.CATEGORY,
    SUM(I.QTY * I.UNIT_PRICE) AS MONTHLY_SALES,
    COUNT(DISTINCT O.ORDER_ID) AS ORDER_CNT
FROM TUNING_ORDERS O
JOIN TUNING_ORDER_ITEM I ON O.ORDER_ID = I.ORDER_ID
JOIN TUNING_PRODUCT P    ON I.PRODUCT_ID = P.PRODUCT_ID
WHERE O.STATUS = 'COMPLETE'
AND O.ORDER_DATE >= ADD_MONTHS(SYSDATE, -12)
GROUP BY TO_CHAR(O.ORDER_DATE, 'YYYY-MM'), P.CATEGORY
HAVING SUM(I.QTY * I.UNIT_PRICE) >= (
    SELECT AVG(MONTHLY_SUM) * 0.5
    FROM (
        SELECT TO_CHAR(O2.ORDER_DATE, 'YYYY-MM') AS MON,
               SUM(I2.QTY * I2.UNIT_PRICE) AS MONTHLY_SUM
        FROM TUNING_ORDERS O2
        JOIN TUNING_ORDER_ITEM I2 ON O2.ORDER_ID = I2.ORDER_ID
        WHERE O2.STATUS = 'COMPLETE'
        GROUP BY TO_CHAR(O2.ORDER_DATE, 'YYYY-MM')
    )
)
ORDER BY ORDER_MONTH DESC, MONTHLY_SALES DESC;

-- ────────────────────────────────────────────
-- [HEAVY-01] 전체 집계 + 분석함수 복합
-- 고객 등급별 주문 순위 + 누적 매출
-- ────────────────────────────────────────────
SELECT
    C.GRADE,
    C.CUSTOMER_NAME,
    C.REGION,
    COUNT(O.ORDER_ID)                                        AS ORDER_CNT,
    SUM(O.TOTAL_AMOUNT)                                      AS TOTAL_SALES,
    RANK() OVER (PARTITION BY C.GRADE ORDER BY SUM(O.TOTAL_AMOUNT) DESC)
                                                             AS GRADE_RANK,
    SUM(SUM(O.TOTAL_AMOUNT)) OVER (PARTITION BY C.GRADE
        ORDER BY SUM(O.TOTAL_AMOUNT) DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)   AS CUM_SALES,
    ROUND(SUM(O.TOTAL_AMOUNT) /
        SUM(SUM(O.TOTAL_AMOUNT)) OVER (PARTITION BY C.GRADE) * 100, 2)
                                                             AS GRADE_SHARE_PCT
FROM TUNING_CUSTOMER C
JOIN TUNING_ORDERS O ON C.CUSTOMER_ID = O.CUSTOMER_ID
WHERE O.STATUS = 'COMPLETE'
AND O.ORDER_DATE BETWEEN ADD_MONTHS(SYSDATE,-12) AND SYSDATE
GROUP BY C.GRADE, C.CUSTOMER_NAME, C.REGION
ORDER BY C.GRADE, GRADE_RANK;

-- ────────────────────────────────────────────
-- [HEAVY-02] WITH + 다중 CTE 조인
-- 상품별 재구매율 분석 (인덱스 없는 PRODUCT_ID 조인)
-- ────────────────────────────────────────────
WITH FIRST_BUY AS (
    SELECT I.PRODUCT_ID,
           O.CUSTOMER_ID,
           MIN(O.ORDER_DATE) AS FIRST_DATE
    FROM TUNING_ORDERS O
    JOIN TUNING_ORDER_ITEM I ON O.ORDER_ID = I.ORDER_ID
    WHERE O.STATUS = 'COMPLETE'
    GROUP BY I.PRODUCT_ID, O.CUSTOMER_ID
),
REPURCHASE AS (
    SELECT I.PRODUCT_ID,
           O.CUSTOMER_ID,
           COUNT(*) AS BUY_CNT
    FROM TUNING_ORDERS O
    JOIN TUNING_ORDER_ITEM I ON O.ORDER_ID = I.ORDER_ID
    WHERE O.STATUS = 'COMPLETE'
    GROUP BY I.PRODUCT_ID, O.CUSTOMER_ID
    HAVING COUNT(*) >= 2
),
PRODUCT_STATS AS (
    SELECT F.PRODUCT_ID,
           COUNT(F.CUSTOMER_ID)               AS TOTAL_BUYERS,
           COUNT(R.CUSTOMER_ID)               AS REPEAT_BUYERS,
           ROUND(COUNT(R.CUSTOMER_ID) /
                 NULLIF(COUNT(F.CUSTOMER_ID),0) * 100, 2) AS REPURCHASE_RATE
    FROM FIRST_BUY F
    LEFT JOIN REPURCHASE R
           ON F.PRODUCT_ID  = R.PRODUCT_ID
          AND F.CUSTOMER_ID = R.CUSTOMER_ID
    GROUP BY F.PRODUCT_ID
)
SELECT
    P.PRODUCT_NAME,
    P.CATEGORY,
    P.PRICE,
    S.TOTAL_BUYERS,
    S.REPEAT_BUYERS,
    S.REPURCHASE_RATE,
    RANK() OVER (PARTITION BY P.CATEGORY ORDER BY S.REPURCHASE_RATE DESC) AS CAT_RANK
FROM PRODUCT_STATS S
JOIN TUNING_PRODUCT P ON S.PRODUCT_ID = P.PRODUCT_ID
WHERE S.TOTAL_BUYERS >= 3
ORDER BY P.CATEGORY, CAT_RANK;

-- ────────────────────────────────────────────
-- [HEAVY-03] UPDATE 서브쿼리 - DML 튜닝 패턴
-- 최근 1년 주문 없는 고객 등급 하향
-- ────────────────────────────────────────────
UPDATE TUNING_CUSTOMER
SET GRADE = 'NORMAL'
WHERE GRADE IN ('VIP', 'GOLD')
AND CUSTOMER_ID NOT IN (
    SELECT DISTINCT CUSTOMER_ID
    FROM TUNING_ORDERS
    WHERE ORDER_DATE >= ADD_MONTHS(SYSDATE, -12)
    AND STATUS = 'COMPLETE'
);
-- ROLLBACK; -- 테스트 후 반드시 롤백