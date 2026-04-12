-- ============================================
-- SQL Tuner v2 - 튜닝 테스트용 테이블 생성
-- ============================================

-- 기존 테이블 제거 (있을 경우)
BEGIN
    FOR t IN (
        SELECT table_name FROM user_tables
        WHERE table_name IN (
            'TUNING_CUSTOMER', 'TUNING_PRODUCT',
            'TUNING_ORDERS', 'TUNING_ORDER_ITEM'
        )
    ) LOOP
        EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' CASCADE CONSTRAINTS';
    END LOOP;
END;
/

-- 고객 테이블
CREATE TABLE TUNING_CUSTOMER (
    CUSTOMER_ID   NUMBER        NOT NULL,
    CUSTOMER_NAME VARCHAR2(100) NOT NULL,
    EMAIL         VARCHAR2(200),
    GRADE         VARCHAR2(10),        -- VIP / GOLD / NORMAL
    JOIN_DATE     DATE,
    REGION        VARCHAR2(50),
    CONSTRAINT PK_TUNING_CUSTOMER PRIMARY KEY (CUSTOMER_ID)
);

-- 상품 테이블
CREATE TABLE TUNING_PRODUCT (
    PRODUCT_ID    NUMBER        NOT NULL,
    PRODUCT_NAME  VARCHAR2(200) NOT NULL,
    CATEGORY      VARCHAR2(50),
    PRICE         NUMBER(10,2),
    STOCK_QTY     NUMBER,
    REG_DATE      DATE,
    CONSTRAINT PK_TUNING_PRODUCT PRIMARY KEY (PRODUCT_ID)
);

-- 주문 테이블
CREATE TABLE TUNING_ORDERS (
    ORDER_ID      NUMBER        NOT NULL,
    CUSTOMER_ID   NUMBER        NOT NULL,
    ORDER_DATE    DATE          NOT NULL,
    STATUS        VARCHAR2(20),        -- PENDING / COMPLETE / CANCEL
    TOTAL_AMOUNT  NUMBER(12,2),
    SHIP_REGION   VARCHAR2(50),
    CONSTRAINT PK_TUNING_ORDERS PRIMARY KEY (ORDER_ID)
);

-- 주문상세 테이블
CREATE TABLE TUNING_ORDER_ITEM (
    ITEM_ID       NUMBER        NOT NULL,
    ORDER_ID      NUMBER        NOT NULL,
    PRODUCT_ID    NUMBER        NOT NULL,
    QTY           NUMBER,
    UNIT_PRICE    NUMBER(10,2),
    DISCOUNT      NUMBER(5,2),
    CONSTRAINT PK_TUNING_ORDER_ITEM PRIMARY KEY (ITEM_ID)
);

COMMIT;