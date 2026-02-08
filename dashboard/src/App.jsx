import { useState, useEffect } from 'react'
import { Activity, Server, Database, Zap, TrendingUp, Clock, DollarSign, RefreshCw, AlertCircle } from 'lucide-react'
import { AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'

const COLORS = ['#3fb950', '#58a6ff', '#d29922', '#f85149']

function App() {
  const [metrics, setMetrics] = useState(null)
  const [budget, setBudget] = useState(null)
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchData = async () => {
    try {
      setLoading(true)
      const [metricsRes, budgetRes, healthRes] = await Promise.all([
        fetch('/api/metrics', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('token') } }),
        fetch('/api/budget', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('token') } }),
        fetch('/api/health')
      ])
      
      if (metricsRes.ok) setMetrics(await metricsRes.json())
      if (budgetRes.ok) setBudget(await budgetRes.json())
      if (healthRes.ok) setHealth(await healthRes.json())
      setError(null)
    } catch (e) {
      setError('Verbindung zum Gateway fehlgeschlagen')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  // Mock data for demo
  const requestsData = [
    { time: '00:00', requests: 12, cached: 8 },
    { time: '04:00', requests: 5, cached: 3 },
    { time: '08:00', requests: 45, cached: 32 },
    { time: '12:00', requests: 78, cached: 56 },
    { time: '16:00', requests: 92, cached: 71 },
    { time: '20:00', requests: 34, cached: 25 },
  ]

  const modelData = [
    { name: 'Local (Llama)', value: 156, color: '#3fb950' },
    { name: 'Claude Sonnet', value: 43, color: '#58a6ff' },
    { name: 'Groq', value: 21, color: '#d29922' },
  ]

  const tierData = [
    { tier: 'LOCAL', requests: 156, cost: 0 },
    { tier: 'CHEAP', requests: 67, cost: 0.12 },
    { tier: 'PREMIUM', requests: 43, cost: 2.45 },
  ]

  const cacheStats = {
    exact_hits: metrics?.cache?.exact_hits || 89,
    semantic_hits: metrics?.cache?.semantic_hits || 45,
    misses: metrics?.cache?.misses || 32,
    total: 166
  }

  const cacheRate = ((cacheStats.exact_hits + cacheStats.semantic_hits) / cacheStats.total * 100).toFixed(1)

  return (
    <div className="min-h-screen bg-github-bg p-4 lg:p-8">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between mb-8 gap-4">
        <div>
          <h1 className="text-2xl lg:text-3xl font-bold flex items-center gap-3">
            <Server className="w-8 h-8 text-github-accent" />
            LLM Gateway Dashboard
          </h1>
          <p className="text-github-muted mt-1">Statistiken und Monitoring</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`badge ${health?.status === 'ok' ? 'badge-success' : 'badge-danger'}`}>
            {health?.status === 'ok' ? '● Online' : '● Offline'}
          </span>
          <button onClick={fetchData} className="btn flex items-center gap-2">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Aktualisieren
          </button>
        </div>
      </div>

      {error && (
        <div className="card mb-6 border-github-danger bg-github-danger/10">
          <div className="flex items-center gap-3 text-github-danger">
            <AlertCircle className="w-5 h-5" />
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          icon={<Zap className="w-6 h-6" />}
          label="Requests heute"
          value={metrics?.requests_today || 266}
          color="text-github-accent"
          bgColor="bg-github-accent/20"
        />
        <StatCard
          icon={<Database className="w-6 h-6" />}
          label="Cache-Rate"
          value={`${cacheRate}%`}
          color="text-github-success"
          bgColor="bg-github-success/20"
        />
        <StatCard
          icon={<DollarSign className="w-6 h-6" />}
          label="Kosten heute"
          value={`$${budget?.daily_spent?.toFixed(2) || '2.57'}`}
          color="text-github-warning"
          bgColor="bg-github-warning/20"
        />
        <StatCard
          icon={<Clock className="w-6 h-6" />}
          label="Avg. Latenz"
          value={`${metrics?.avg_latency_ms || 245}ms`}
          color="text-github-muted"
          bgColor="bg-github-muted/20"
        />
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Requests Over Time */}
        <div className="card">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-github-accent" />
            Requests über Zeit
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={requestsData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
              <XAxis dataKey="time" stroke="#8b949e" fontSize={12} />
              <YAxis stroke="#8b949e" fontSize={12} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '6px' }}
                labelStyle={{ color: '#c9d1d9' }}
              />
              <Area type="monotone" dataKey="requests" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.3} name="Gesamt" />
              <Area type="monotone" dataKey="cached" stroke="#3fb950" fill="#3fb950" fillOpacity={0.3} name="Cached" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Model Distribution */}
        <div className="card">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Activity className="w-5 h-5 text-github-accent" />
            Modell-Verteilung
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie
                data={modelData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={100}
                paddingAngle={2}
                dataKey="value"
                label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                labelLine={false}
              >
                {modelData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip 
                contentStyle={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '6px' }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Tier & Cache Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Tier Distribution */}
        <div className="card">
          <h3 className="text-lg font-semibold mb-4">Tier-Statistiken</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={tierData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
              <XAxis type="number" stroke="#8b949e" fontSize={12} />
              <YAxis type="category" dataKey="tier" stroke="#8b949e" fontSize={12} width={80} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '6px' }}
                formatter={(value, name) => [name === 'cost' ? `$${value}` : value, name === 'cost' ? 'Kosten' : 'Requests']}
              />
              <Bar dataKey="requests" fill="#58a6ff" name="Requests" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-4 grid grid-cols-3 gap-4 text-center text-sm">
            {tierData.map(t => (
              <div key={t.tier}>
                <div className="text-github-muted">{t.tier}</div>
                <div className="font-semibold">${t.cost.toFixed(2)}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Cache Stats */}
        <div className="card">
          <h3 className="text-lg font-semibold mb-4">Cache-Statistiken</h3>
          <div className="space-y-4">
            <CacheBar label="Exact Cache" value={cacheStats.exact_hits} total={cacheStats.total} color="bg-github-success" />
            <CacheBar label="Semantic Cache" value={cacheStats.semantic_hits} total={cacheStats.total} color="bg-github-accent" />
            <CacheBar label="Cache Miss" value={cacheStats.misses} total={cacheStats.total} color="bg-github-danger" />
          </div>
          <div className="mt-6 p-4 bg-github-bg rounded-lg">
            <div className="flex justify-between items-center">
              <span className="text-github-muted">Gesamte Cache-Rate</span>
              <span className="text-2xl font-bold text-github-success">{cacheRate}%</span>
            </div>
            <p className="text-xs text-github-muted mt-2">
              {cacheStats.exact_hits + cacheStats.semantic_hits} von {cacheStats.total} Anfragen aus Cache beantwortet
            </p>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-8 text-center text-github-muted text-sm">
        LLM Gateway v2.0 • Letzte Aktualisierung: {new Date().toLocaleTimeString('de-DE')}
      </div>
    </div>
  )
}

function StatCard({ icon, label, value, color, bgColor }) {
  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg ${bgColor}`}>
          <div className={color}>{icon}</div>
        </div>
        <div>
          <div className="text-xs text-github-muted">{label}</div>
          <div className="text-xl font-bold">{value}</div>
        </div>
      </div>
    </div>
  )
}

function CacheBar({ label, value, total, color }) {
  const percent = (value / total * 100).toFixed(1)
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span>{label}</span>
        <span className="text-github-muted">{value} ({percent}%)</span>
      </div>
      <div className="h-2 bg-github-bg rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

export default App
