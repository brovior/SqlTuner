-- ============================================
-- SQL Tuner v2 - 인덱스 생성
-- 일부러 인덱스 없는 컬럼도 남겨둠 (FTS 테스트용)
-- ============================================

-- TUNING_ORDERS: 자주 쓰는 컬럼만 인덱스 생성
CREATE INDEX IDX_ORDERS_CUSTOMER  ON TUNING_ORDERS (CUSTOMER_ID);
CREATE INDEX IDX_ORDERS_DATE      ON TUNING_ORDERS (ORDER_DATE);

-- TUNING_ORDER_ITEM: 조인 컬럼만
CREATE INDEX IDX_ITEM_ORDER       ON TUNING_ORDER_ITEM (ORDER_ID);

-- 아래는 의도적으로 인덱스 없음 (튜닝 테스트용)
-- TUNING_ORDERS.STATUS       → FTS 테스트
-- TUNING_ORDERS.TOTAL_AMOUNT → 범위 조건 FTS 테스트
-- TUNING_CUSTOMER.GRADE      → IN/서브쿼리 테스트
-- TUNING_ORDER_ITEM.PRODUCT_ID → 조인 테스트

COMMIT;