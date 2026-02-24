import { useEffect, useState } from 'react'
import { Plus, Trash2, Edit2 } from 'lucide-react'
import api from '../api/client'
import { useLanguage } from '../contexts/LanguageContext'

interface LoadBalancer {
  id: string
  name: string
  iran_node_id: string
  tunnel_ids: string[]
  listen_port: number
  algorithm: string
  status: string
  error_message?: string | null
  created_at: string
  updated_at: string
}

interface Node {
  id: string
  name: string
  metadata?: {
    ip_address?: string
    role?: string
  }
}

interface Tunnel {
  id: string
  name: string
  iran_node_id: string | null
  type: string
  spec: Record<string, any>
}

const LoadBalancers = () => {
  const { t } = useLanguage()
  const [loadBalancers, setLoadBalancers] = useState<LoadBalancer[]>([])
  const [nodes, setNodes] = useState<Node[]>([])
  const [tunnels, setTunnels] = useState<Tunnel[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<LoadBalancer | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    iran_node_id: '',
    tunnel_ids: [] as string[],
    listen_port: '',
    algorithm: 'round_robin',
  })

  useEffect(() => {
    fetchLoadBalancers()
    fetchNodes()
    fetchTunnels()
  }, [])

  const fetchLoadBalancers = async () => {
    try {
      const response = await api.get('/load-balancers')
      setLoadBalancers(response.data)
    } catch (error) {
      console.error('Failed to fetch load balancers:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchNodes = async () => {
    try {
      const response = await api.get('/nodes')
      const iranNodes = response.data.filter((node: Node) => node.metadata?.role === 'iran')
      setNodes(iranNodes)
    } catch (error) {
      console.error('Failed to fetch nodes:', error)
    }
  }

  const fetchTunnels = async () => {
    try {
      const response = await api.get('/tunnels')
      const reverseTunnels = response.data.filter((tunnel: Tunnel) => tunnel.iran_node_id)
      setTunnels(reverseTunnels)
    } catch (error) {
      console.error('Failed to fetch tunnels:', error)
    }
  }

  const handleCreate = () => {
    setEditing(null)
    setFormData({
      name: '',
      iran_node_id: '',
      tunnel_ids: [],
      listen_port: '',
      algorithm: 'round_robin',
    })
    setShowModal(true)
  }

  const handleEdit = (lb: LoadBalancer) => {
    setEditing(lb)
    setFormData({
      name: lb.name,
      iran_node_id: lb.iran_node_id,
      tunnel_ids: lb.tunnel_ids,
      listen_port: lb.listen_port.toString(),
      algorithm: lb.algorithm,
    })
    setShowModal(true)
  }

  const handleDelete = async (id: string) => {
    if (!confirm(t.loadBalancers.confirmDelete)) return

    try {
      await api.delete(`/load-balancers/${id}`)
      fetchLoadBalancers()
    } catch (error) {
      console.error('Failed to delete load balancer:', error)
      alert(t.loadBalancers.deleteError)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    try {
      const data = {
        name: formData.name,
        iran_node_id: formData.iran_node_id,
        tunnel_ids: formData.tunnel_ids,
        listen_port: parseInt(formData.listen_port),
        algorithm: formData.algorithm,
      }

      if (editing) {
        await api.put(`/load-balancers/${editing.id}`, data)
      } else {
        await api.post('/load-balancers', data)
      }

      setShowModal(false)
      fetchLoadBalancers()
    } catch (error: any) {
      console.error('Failed to save load balancer:', error)
      alert(error.response?.data?.detail || t.loadBalancers.saveError)
    }
  }

  const getNodeName = (nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId)
    return node ? node.name : nodeId
  }

  const getNodeIP = (nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId)
    return node?.metadata?.ip_address || 'N/A'
  }

  const getTunnelName = (tunnelId: string) => {
    const tunnel = tunnels.find((t) => t.id === tunnelId)
    return tunnel ? tunnel.name : tunnelId
  }

  const getAvailableTunnels = () => {
    if (!formData.iran_node_id) return []
    return tunnels.filter((tunnel) => tunnel.iran_node_id && tunnel.iran_node_id !== formData.iran_node_id)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500 dark:text-gray-400">{t.loadBalancers.loading}</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">{t.loadBalancers.title}</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">{t.loadBalancers.subtitle}</p>
        </div>
        <button
          onClick={handleCreate}
          className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={20} />
          <span>{t.loadBalancers.create}</span>
        </button>
      </div>

      {loadBalancers.length === 0 ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          {t.loadBalancers.noLoadBalancers}
        </div>
      ) : (
        <div className="grid gap-4">
          {loadBalancers.map((lb) => (
            <div
              key={lb.id}
              className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-200 dark:border-gray-700"
            >
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <div className="flex items-center space-x-3 mb-2">
                    <h3 className="text-xl font-semibold text-gray-900 dark:text-white">{lb.name}</h3>
                    <span
                      className={`px-2 py-1 rounded text-sm ${
                        lb.status === 'active'
                          ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                          : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                      }`}
                    >
                      {lb.status}
                    </span>
                  </div>
                  <div className="space-y-1 text-sm text-gray-600 dark:text-gray-400">
                    <p>
                      <span className="font-medium">{t.loadBalancers.iranNode}:</span> {getNodeName(lb.iran_node_id)} ({getNodeIP(lb.iran_node_id)})
                    </p>
                    <p>
                      <span className="font-medium">{t.loadBalancers.listenPort}:</span> {lb.listen_port}
                    </p>
                    <p>
                      <span className="font-medium">{t.loadBalancers.algorithm}:</span> {lb.algorithm}
                    </p>
                    <p>
                      <span className="font-medium">{t.loadBalancers.tunnels}:</span>{' '}
                      {lb.tunnel_ids.map((tid) => getTunnelName(tid)).join(', ')}
                    </p>
                    {lb.error_message && (
                      <p className="text-red-600 dark:text-red-400">
                        <span className="font-medium">{t.loadBalancers.error}:</span> {lb.error_message}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex space-x-2">
                  <button
                    onClick={() => handleEdit(lb)}
                    className="p-2 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded"
                  >
                    <Edit2 size={18} />
                  </button>
                  <button
                    onClick={() => handleDelete(lb.id)}
                    className="p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded"
                  >
                    <Trash2 size={18} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <h2 className="text-2xl font-bold mb-4 text-gray-900 dark:text-white">
              {editing ? t.loadBalancers.edit : t.loadBalancers.create}
            </h2>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {t.loadBalancers.name}
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {t.loadBalancers.iranNode}
                </label>
                <select
                  value={formData.iran_node_id}
                  onChange={(e) => setFormData({ ...formData, iran_node_id: e.target.value, tunnel_ids: [] })}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                  required
                >
                  <option value="">{t.loadBalancers.selectIranNode}</option>
                  {nodes.map((node) => (
                    <option key={node.id} value={node.id}>
                      {node.name} ({node.metadata?.ip_address || 'N/A'})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {t.loadBalancers.listenPort}
                </label>
                <input
                  type="number"
                  value={formData.listen_port}
                  onChange={(e) => setFormData({ ...formData, listen_port: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                  required
                  min="1"
                  max="65535"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {t.loadBalancers.algorithm}
                </label>
                <select
                  value={formData.algorithm}
                  onChange={(e) => setFormData({ ...formData, algorithm: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                >
                  <option value="round_robin">Round Robin</option>
                  <option value="least_conn">Least Connections</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {t.loadBalancers.tunnels}
                </label>
                <div className="border border-gray-300 dark:border-gray-600 rounded-lg p-3 max-h-48 overflow-y-auto">
                  {getAvailableTunnels().length === 0 ? (
                    <p className="text-gray-500 dark:text-gray-400 text-sm">
                      {formData.iran_node_id ? t.loadBalancers.noTunnelsOnOtherNodes : t.loadBalancers.selectIranNodeFirst}
                    </p>
                  ) : (
                    getAvailableTunnels().map((tunnel) => (
                      <label key={tunnel.id} className="flex items-center space-x-2 py-1">
                        <input
                          type="checkbox"
                          checked={formData.tunnel_ids.includes(tunnel.id)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setFormData({ ...formData, tunnel_ids: [...formData.tunnel_ids, tunnel.id] })
                            } else {
                              setFormData({
                                ...formData,
                                tunnel_ids: formData.tunnel_ids.filter((id) => id !== tunnel.id),
                              })
                            }
                          }}
                          className="rounded"
                        />
                        <span className="text-sm text-gray-700 dark:text-gray-300">
                          {tunnel.name} ({tunnel.type})
                        </span>
                      </label>
                    ))
                  )}
                </div>
              </div>

              <div className="flex justify-end space-x-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
                >
                  {t.loadBalancers.cancel}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  {editing ? t.loadBalancers.update : t.loadBalancers.create}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default LoadBalancers

