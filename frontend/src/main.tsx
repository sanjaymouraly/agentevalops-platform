import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import App from './App'
import Overview from './pages/Overview'
import Experiments from './pages/Experiments'
import ExperimentDetail from './pages/ExperimentDetail'
import Benchmarks from './pages/Benchmarks'
import Agents from './pages/Agents'
import Providers from './pages/Providers'
import Compare from './pages/Compare'
import Failures from './pages/Failures'
import Security from './pages/Security'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<Overview />} />
          <Route path="experiments" element={<Experiments />} />
          <Route path="experiments/:id" element={<ExperimentDetail />} />
          <Route path="benchmarks" element={<Benchmarks />} />
          <Route path="agents" element={<Agents />} />
          <Route path="providers" element={<Providers />} />
          <Route path="compare" element={<Compare />} />
          <Route path="failures" element={<Failures />} />
          <Route path="security" element={<Security />} />
          <Route path="reports" element={<Reports />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)