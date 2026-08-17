import { createContext, useContext, useState, useCallback, useMemo } from 'react';

export const DEFAULT_SYMBOL = 'XAUUSD';

export const SYMBOL_LIST = [
  ['XAUUSD', 'Gold / US Dollar'],
  ['EURUSD', 'Euro / US Dollar'],
  ['GBPUSD', 'British Pound / US Dollar'],
  ['USDJPY', 'US Dollar / Japanese Yen'],
  ['BTCUSD', 'Bitcoin / US Dollar'],
  ['ETHUSD', 'Ethereum / US Dollar'],
  ['US500', 'S&P 500 Index'],
  ['NAS100', 'Nasdaq 100 Index'],
  ['US30', 'Dow Jones 30 Index'],
  ['WTI', 'Crude Oil'],
  ['AAPL', 'Apple Inc.'],
  ['TSLA', 'Tesla Inc.']
];

const STORAGE_KEY = 'quantos.activeSymbol';

const SymbolContext = createContext(null);

export function SymbolProvider({ children }) {
  const [symbol, setSymbolState] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || DEFAULT_SYMBOL;
    } catch (e) {
      return DEFAULT_SYMBOL;
    }
  });

  const setSymbol = useCallback((sym) => {
    const value = (sym || DEFAULT_SYMBOL).toUpperCase();
    setSymbolState(value);
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch (e) { /* storage unavailable */ }
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get('symbol') !== value) {
        url.searchParams.set('symbol', value);
        window.history.replaceState({}, '', url);
      }
    } catch (e) { /* history unavailable */ }
  }, []);

  const value = useMemo(() => ({ symbol, setSymbol }), [symbol, setSymbol]);
  return <SymbolContext.Provider value={value}>{children}</SymbolContext.Provider>;
}

export function useSymbol() {
  const ctx = useContext(SymbolContext);
  if (!ctx) {
    // Fallback when used outside the provider (should not happen).
    return { symbol: DEFAULT_SYMBOL, setSymbol: () => {} };
  }
  return ctx;
}
