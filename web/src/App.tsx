import { Route, Routes } from 'react-router-dom';
import { RequireAuth } from './auth/RequireAuth';
import { LoginPage } from './auth/LoginPage';
import { AppLayout } from './components/AppLayout';
import { OverviewPage } from './pages/OverviewPage';
import { GamesPage } from './pages/GamesPage';
import { GameDetailPage } from './pages/GameDetailPage';
import { BlownLeadsPage } from './pages/BlownLeadsPage';
import { MatchRatesPage } from './pages/MatchRatesPage';
import { AliasesPage } from './pages/AliasesPage';
import { MarketTypesPage } from './pages/MarketTypesPage';
import { ExportPage } from './pages/ExportPage';
import { NotFoundPage } from './pages/NotFoundPage';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="games" element={<GamesPage />} />
          <Route path="games/:id" element={<GameDetailPage />} />
          <Route path="blown-leads" element={<BlownLeadsPage />} />
          <Route path="match-rates" element={<MatchRatesPage />} />
          <Route path="aliases" element={<AliasesPage />} />
          <Route path="market-types" element={<MarketTypesPage />} />
          <Route path="export" element={<ExportPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
