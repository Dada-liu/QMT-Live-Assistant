/**
 * 证券券种工具（与后端 backend/utils.py 同一套代码段规则）。
 *
 * 可转债/可交换债：沪市 110/111/113/118/132，深市 123/127/128/117。
 * 最小交易单位：股票 100 股/手，可转债 10 张/手。
 */

export const SECURITY_TYPE_STOCK = 'stock';
export const SECURITY_TYPE_CONVERTIBLE_BOND = 'convertible_bond';

export const SECURITY_TYPE_NAMES = {
    [SECURITY_TYPE_STOCK]: '股票',
    [SECURITY_TYPE_CONVERTIBLE_BOND]: '可转债',
};

const CONVERTIBLE_BOND_PREFIXES = {
    SH: ['110', '111', '113', '118', '132'],
    SZ: ['123', '127', '128', '117'],
};

const STOCK_LOT_SIZE = 100;
const CONVERTIBLE_BOND_LOT_SIZE = 10;

const STOCK_TICK_SIZE = 0.01;
const CONVERTIBLE_BOND_TICK_SIZE = 0.001;

/** 判断证券代码是否为可转债/可交换债（QMT 或聚宽格式后缀均可） */
export function isConvertibleBond(stockCode) {
    const code = (stockCode || '').trim().toUpperCase();
    const dotIndex = code.lastIndexOf('.');
    if (dotIndex < 0) return false;
    const number = code.slice(0, dotIndex);
    const suffix = code.slice(dotIndex + 1);
    // 聚宽格式归一：XSHG→SH，XSHE→SZ
    const market = suffix === 'XSHG' ? 'SH' : suffix === 'XSHE' ? 'SZ' : suffix;
    const prefixes = CONVERTIBLE_BOND_PREFIXES[market];
    return !!prefixes && prefixes.some(p => number.startsWith(p));
}

/** 最小交易单位（每手数量）：可转债 10 张，股票 100 股 */
export function getLotSize(stockCode) {
    return isConvertibleBond(stockCode) ? CONVERTIBLE_BOND_LOT_SIZE : STOCK_LOT_SIZE;
}

/** 委托数量单位：可转债为"张"，其余为"股" */
export function getQuantityUnit(stockCode) {
    return isConvertibleBond(stockCode) ? '张' : '股';
}

/** 最小变动价位（tick）：可转债 0.001 元，股票 0.01 元 */
export function getTickSize(stockCode) {
    return isConvertibleBond(stockCode) ? CONVERTIBLE_BOND_TICK_SIZE : STOCK_TICK_SIZE;
}

/** 限价价格允许的最大小数位：股票 2 位，可转债 3 位 */
export function getPriceDecimalPlaces(stockCode) {
    return isConvertibleBond(stockCode) ? 3 : 2;
}

/** 校验价格是否符合最小变动价位（tick）精度；epsilon 比较避免浮点误差误判（如 12.55） */
export function isTickAlignedPrice(price, stockCode) {
    const tick = getTickSize(stockCode);
    const scaled = price / tick;
    return Math.abs(scaled - Math.round(scaled)) <= 1e-6;
}

/** 策略种类中文名 */
export function getSecurityTypeName(securityType) {
    return SECURITY_TYPE_NAMES[securityType] || SECURITY_TYPE_NAMES[SECURITY_TYPE_STOCK];
}
