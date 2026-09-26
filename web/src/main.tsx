import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './styles.css'
import Landing from './pages/Landing'
import CoopPage from './pages/Coop'
import NodePage from './pages/Node'
import { registerWorker } from './lib/push'

registerWorker().catch(() => {})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/coop/:coopId" element={<CoopPage />} />
        <Route path="/call" element={<CoopPage />} />
        <Route path="/node/:coopId" element={<NodePage />} />
        <Route path="*" element={<Landing />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
