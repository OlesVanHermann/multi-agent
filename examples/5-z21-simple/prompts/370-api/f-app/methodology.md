# Methodology — f-app

## Pattern d'implémentation

### Client axios avec token Keycloak

```javascript
// api/client.js
import axios from 'axios'
import keycloak from '../keycloak'

const client = axios.create({ baseURL: import.meta.env.VITE_API_URL })

client.interceptors.request.use(async (config) => {
  await keycloak.updateToken(30)
  config.headers.Authorization = `Bearer ${keycloak.token}`
  return config
})

export default client
```

### Hook useItems

```javascript
// hooks/useItems.js
export function useItems() {
  const [items, setItems] = useState([])

  const fetchItems = async () => {
    const { data } = await client.get('/items/')
    setItems(data)
  }

  const createItem = async (name, data = {}) => {
    const { data: item } = await client.post('/items/', { name, data })
    setItems(prev => [...prev, item])
    return item
  }

  const deleteItem = async (id) => {
    await client.delete(`/items/${id}`)
    setItems(prev => prev.filter(i => i.id !== id))
  }

  useEffect(() => { fetchItems() }, [])
  return { items, createItem, deleteItem, fetchItems }
}
```

### Protection de route

```jsx
// App.jsx
function ProtectedRoute({ children }) {
  const { keycloak, initialized } = useKeycloak()
  if (!initialized) return <div>Loading...</div>
  if (!keycloak.authenticated) {
    keycloak.login()
    return null
  }
  return children
}
```

## Règles apprises

_(vide au démarrage — le Coach ajoute ici si un pattern d'erreur apparaît 3x)_
