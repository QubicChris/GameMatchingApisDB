import { Route, Routes } from 'react-router-dom';
import { RequireAuth } from './auth/RequireAuth';
import { LoginPage } from './auth/LoginPage';
import { AppLayout } from './components/AppLayout';
import { OverviewPage } from './pages/OverviewPage';
import { ComingSoonPage } from './pages/ComingSoonPage';
import { NotFoundPage } from './pages/NotFoundPage';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="games" element={<ComingSoonPage title="Games" />} />
          <Route path="games/:id" element={<ComingSoonPage title="Game" />} />
          <Route path="blown-leads" element={<ComingSoonPage title="Blown Leads" />} />
          <Route path="match-rates" element={<ComingSoonPage title="Match Rates" />} />
          <Route path="aliases" element={<ComingSoonPage title="Team Aliases" />} />
          <Route path="market-types" element={<ComingSoonPage title="Market Types" />} />
          <Route path="export" element={<ComingSoonPage title="Export" />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
