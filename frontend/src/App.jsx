import { Routes, Route, Link, useLocation } from 'react-router-dom';
import Dashboard from './pages/Dashboard.jsx';
import MarketData from './pages/MarketData.jsx';
import News from './pages/News.jsx';
import Economic from './pages/Economic.jsx';
import Macro from './pages/Macro.jsx';
import Technical from './pages/Technical.jsx';
import SmartMoney from './pages/SmartMoney.jsx';
import AIDecision from './pages/AIDecision.jsx';
import Agents from './pages/Agents.jsx';
import Debate from './pages/Debate.jsx';
import RiskDebate from './pages/RiskDebate.jsx';
import TradingControl from './pages/TradingControl.jsx';
import Trading from './pages/Trading.jsx';
import Portfolio from './pages/Portfolio.jsx';
import Backtest from './pages/Backtest.jsx';
import Historical from './pages/Historical.jsx';
import Alerts from './pages/Alerts.jsx';
import Reports from './pages/Reports.jsx';
import Research from './pages/Research.jsx';
import SystemAdmin from './pages/SystemAdmin.jsx';
import CloudInfrastructure from './pages/CloudInfrastructure.jsx';
import DevOps from './pages/DevOps.jsx';
import ProductionReadiness from './pages/ProductionReadiness.jsx';
import SystemValidation from './pages/SystemValidation.jsx';
import Connections from './pages/Connections.jsx';
import AdminControl from './pages/AdminControl.jsx';
import AgentCommandCenter from './pages/AgentCommandCenter.jsx';
import ProIndicators from './pages/ProIndicators.jsx';
import QuantStats from './pages/QuantStats.jsx';
import FixedIncome from './pages/FixedIncome.jsx';
import SmartMoneyIntel from './pages/SmartMoneyIntel.jsx';
import PredictionMarkets from './pages/PredictionMarkets.jsx';
import PortfolioOptimizer from './pages/PortfolioOptimizer.jsx';
import PriceForecast from './pages/PriceForecast.jsx';
import AdvancedOrders from './pages/AdvancedOrders.jsx';

const NAV = [
  { section: 'Command Center', items: [
    { path: '/trading-control', label: 'Trading Control', icon: '◈', batch: 'B13' },
    { path: '/', label: 'Live Dashboard', icon: '◈', batch: 'B01-02' }
  ]},
  { section: 'Intelligence', items: [
    { path: '/news', label: 'News Terminal', icon: '▣', batch: 'B03' },
    { path: '/economic', label: 'Economic Calendar', icon: '▤', batch: 'B05' },
    { path: '/macro', label: 'Macro Intelligence', icon: '◉', batch: 'B11' },
    { path: '/historical', label: 'Historical Intel', icon: '▦', batch: 'B06' },
    { path: '/fixed-income', label: 'Fixed Income', icon: '⌃', batch: 'PRO' }
  ]},
  { section: 'Markets', items: [
    { path: '/market', label: 'Market Data Engine', icon: '◈', batch: 'B04' },
    { path: '/technical', label: 'Technical Analysis', icon: '◮', batch: 'B08' },
    { path: '/smc', label: 'Smart Money', icon: '◭', batch: 'B09' },
    { path: '/pro-indicators', label: 'Pro Indicators', icon: '☯', batch: 'PRO' },
    { path: '/quant-stats', label: 'Quant Stats', icon: '∿', batch: 'PRO' },
    { path: '/prediction-markets', label: 'Prediction Markets', icon: '◬', batch: 'PRO' },
    { path: '/portfolio-optimizer', label: 'Portfolio Optimizer', icon: '▨', batch: 'PRO' },
    { path: '/price-forecast', label: 'AI Price Forecast', icon: '∿', batch: 'PRO' },
    { path: '/institutional', label: 'Smart Money Intel', icon: '◬', batch: 'PRO' }
  ]},
  { section: 'AI', items: [
    { path: '/ai', label: 'AI Decision Center', icon: '✦', batch: 'B07' },
    { path: '/agents', label: 'AI Agents', icon: '✧', batch: 'B07' },
    { path: '/agent-command-center', label: 'Agent Command Center', icon: '◉', batch: 'PRO' },
    { path: '/debate', label: 'Bull vs Bear Debate', icon: '⚖', batch: 'B43' },
    { path: '/risk-debate', label: 'Risk Debate Team', icon: '⚔', batch: 'B44' }
  ]},
  { section: 'Execution', items: [
    { path: '/trading', label: 'Trading Engine + MT5', icon: '⇄', batch: 'B12-22' },
    { path: '/portfolio', label: 'Portfolio', icon: '▨', batch: 'B17-18' },
    { path: '/backtest', label: 'Backtesting Lab', icon: '▤', batch: 'B20' },
    { path: '/advanced-orders', label: 'Advanced Orders', icon: '⇄', batch: 'PRO' }
  ]},
  { section: 'Integrations', items: [
    { path: '/connections', label: 'Connections', icon: '⇌', batch: 'B42' }
  ]},
  { section: 'Control Panel', items: [
    { path: '/admin', label: 'Admin Control', icon: '⚙', batch: 'A1' }
  ]},
  { section: 'Operations', items: [
    { path: '/alerts', label: 'Alerts & Notifications', icon: '❒', batch: 'B24' },
    { path: '/reports', label: 'Reports', icon: '▧', batch: 'B25' },
    { path: '/research', label: 'Research Lab', icon: '⬢', batch: 'B26-28' },
    { path: '/system', label: 'Admin & Infrastructure', icon: '⚙', batch: 'B29-37' }
  ]},
  { section: 'Enterprise', items: [
    { path: '/cloud', label: 'Cloud Infrastructure', icon: '☁', batch: 'B38' },
    { path: '/devops', label: 'DevOps & CI/CD', icon: '⇶', batch: 'B39' },
    { path: '/production', label: 'Production Readiness', icon: '▲', batch: 'B40' },
    { path: '/validation', label: 'System Validation', icon: '✓', batch: 'B41' }
  ]}
];

function Sidebar({ onNavigate }) {
  const { pathname } = useLocation();
  return (
    <aside className="sidebar">
      <div className="logo">
        <div className="logo-mark">ZQ</div>
        <div className="logo-text">
          <h1>ZZ_QuantOS</h1>
          <span>AI BOAT · Operating System</span>
        </div>
      </div>
      <nav>
        {NAV.map((section) => (
          <div key={section.section} className="nav-section">
            <div className={`nav-heading${section.section === 'AI' ? ' nav-heading-ai' : ''}`}>{section.section}</div>
            {section.items.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                onClick={onNavigate}
                className={`nav-item ${pathname === item.path ? 'active' : ''}`}
              >
                <span className="nav-icon">{item.icon}</span>
                <span className="nav-label">{item.label}</span>
                <span className="nav-batch">{item.batch}</span>
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="status-dot" /> System Online
        <span className="ver">v1.0.0</span>
      </div>
    </aside>
  );
}

function Header({ title }) {
  return (
    <header className="topbar">
      <div className="topbar-title">{title}</div>
      <div className="topbar-meta">
        <span className="pill" id="clock" />
        <span className="pill">Port 3001 · Live</span>
        <span className="pill accent">AI Engine Active</span>
      </div>
    </header>
  );
}

export default function App() {
  const { pathname } = useLocation();
  const titles = {
    '/': 'Live Dashboard · Enterprise Command Center',
    '/trading-control': 'Trading Control · Mode & Risk Override',
    '/news': 'News Intelligence Terminal',
    '/economic': 'Economic Calendar Intelligence',
    '/macro': 'Macro Intelligence',
    '/historical': 'Historical Intelligence',
    '/fixed-income': 'Fixed Income · US Treasury Curve, Spreads, FRED',
    '/market': 'Market Data Engine',
    '/technical': 'Enterprise Technical Analysis Engine',
    '/pro-indicators': 'Pro Indicators · Ichimoku, DeMark, Vol Cones, RRG',
    '/quant-stats': 'Quant Stats · CAPM, Normality, Unit-Root, Cointegration, OLS',
    '/prediction-markets': 'Prediction Markets · Market-Implied Probabilities (Polymarket)',
    '/portfolio-optimizer': 'Portfolio Optimizer · HRP / CVaR Allocation & Stress-Testing',
    '/price-forecast': 'AI Price Forecast · Kronos Foundation-Model Path Forecast',
    '/advanced-orders': 'Advanced Orders · Order Types + Pre-Trade Checklist',
    '/institutional': 'Smart Money Intel · Short Interest, Dark Pool, COT, SEC',
    '/smc': 'Smart Money Concepts',
    '/ai': 'AI Decision Center · Multi-Agent Consensus',
    '/agents': 'AI Agents Management · Core & Custom Consensus',
    '/agent-command-center': 'Agent Command Center · Live Agent Status',
    '/debate': 'Bull vs Bear Research Debate',
    '/risk-debate': 'Risk Debate Team · Portfolio Gate',
    '/trading': 'Trading Engine & MT5 Integration',
    '/portfolio': 'Portfolio Management',
    '/backtest': 'Backtesting & Strategy Validation',
    '/alerts': 'Alerts & Notifications Center',
    '/reports': 'Report Generation Studio',
    '/research': 'Research Laboratory & Data Pipelines',
    '/system': 'Admin · Security · Infrastructure',
    '/cloud': 'Cloud Infrastructure Management',
    '/devops': 'DevOps & CI/CD Pipeline Center',
    '/production': 'Production Readiness & Go-Live',
    '/validation': 'Enterprise System Validation & Certification',
    '/connections': 'Connections & Integrations',
    '/admin': 'Admin Control Panel'
  };
  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <Header title={titles[pathname] || 'ZZ_QuantOS AI BOAT'} />
        <div className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/news" element={<News />} />
            <Route path="/economic" element={<Economic />} />
            <Route path="/macro" element={<Macro />} />
            <Route path="/historical" element={<Historical />} />
            <Route path="/fixed-income" element={<FixedIncome />} />
            <Route path="/market" element={<MarketData />} />
            <Route path="/technical" element={<Technical />} />
            <Route path="/pro-indicators" element={<ProIndicators />} />
            <Route path="/quant-stats" element={<QuantStats />} />
            <Route path="/prediction-markets" element={<PredictionMarkets />} />
            <Route path="/portfolio-optimizer" element={<PortfolioOptimizer />} />
            <Route path="/price-forecast" element={<PriceForecast />} />
            <Route path="/advanced-orders" element={<AdvancedOrders />} />
            <Route path="/institutional" element={<SmartMoneyIntel />} />
            <Route path="/smc" element={<SmartMoney />} />
            <Route path="/ai" element={<AIDecision />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/agent-command-center" element={<AgentCommandCenter />} />
            <Route path="/debate" element={<Debate />} />
            <Route path="/risk-debate" element={<RiskDebate />} />
            <Route path="/trading-control" element={<TradingControl />} />
            <Route path="/trading" element={<Trading />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/research" element={<Research />} />
            <Route path="/system" element={<SystemAdmin />} />
            <Route path="/cloud" element={<CloudInfrastructure />} />
            <Route path="/devops" element={<DevOps />} />
            <Route path="/production" element={<ProductionReadiness />} />
            <Route path="/validation" element={<SystemValidation />} />
            <Route path="/connections" element={<Connections />} />
            <Route path="/admin" element={<AdminControl />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
