# python -m uvicorn main:app --reload
# c:
# cd \Users\willi

#Documentación interactiva: http://127.0.0.1:8000/docs#/ (127.0.0.1 in Bing)
#Documentación alternativa (ReDoc): http://127.0.0.1:8000/redoc #·(127.0.0.1 in Bing)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
import sqlite3

app = FastAPI(title="Omnicheck API", description="API REST para control de asistencia distribuido", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permite que cualquier frontend se conecte (ideal para desarrollo y Vercel)
    allow_credentials=True,
    allow_methods=["*"], # Permite GET, POST, PUT, DELETE, etc.
    allow_headers=["*"], # Permite cualquier cabecera
)

# --- MODELOS DE DATOS (Pydantic) ---
class CheckRequest(BaseModel):
    user_id: str
    action: str  # "CLOCK_IN" o "CLOCK_OUT"
    device_id: str
    location_context: str

class UserResponse(BaseModel):
    user_id: str
    name: str
    role: str
    status: str
    last_clock_in: Optional[str] = None

class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None

class UserCreate(BaseModel):
    id: str
    name: str
    role: str

# --- CONFIGURACIÓN DE BASE DE DATOS (SQLite) ---
# Al usar un archivo en lugar de :memory:, los datos persisten al reiniciar.
conn = sqlite3.connect("omnicheck.db", check_same_thread=False)
conn.row_factory = sqlite3.Row  # Permite que las filas se comporten como diccionarios
cursor = conn.cursor()

# 1. TABLA: Usuarios
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT,
    role TEXT,
    status TEXT,
    last_clock_in TEXT
)
""")

# 2. TABLA: Dispositivos
cursor.execute("""
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    description TEXT,
    is_active INTEGER
)
""")

# 3. TABLA: Historial de Asistencia
cursor.execute("""
CREATE TABLE IF NOT EXISTS attendance_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    action TEXT,
    device_id TEXT,
    location_context TEXT,
    timestamp TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(device_id) REFERENCES devices(id)
)
""")

# --- DATOS SEMILLA ---
# Usamos INSERT OR IGNORE para que no se dupliquen cada vez que reinicias el servidor
cursor.execute("INSERT OR IGNORE INTO users (id, name, role, status, last_clock_in) VALUES ('5520', 'Usuario Ejemplo', 'Employee', 'INACTIVE', NULL)")
cursor.execute("INSERT OR IGNORE INTO users (id, name, role, status, last_clock_in) VALUES ('1010', 'Ana Supervisora', 'Supervisor', 'INACTIVE', NULL)")

cursor.execute("INSERT OR IGNORE INTO devices (id, description, is_active) VALUES ('TERM-NORTH-01', 'Terminal Entrada Norte', 1)")
cursor.execute("INSERT OR IGNORE INTO devices (id, description, is_active) VALUES ('APP-MOB-01', 'App Móvil RH', 1)")

conn.commit()


# --- ENDPOINTS ---

@app.post("/api/v1/attendance/check", status_code=201)
def register_check(request: CheckRequest):
    # 1. Validar Usuario
    cursor.execute("SELECT * FROM users WHERE id=?", (request.user_id,))
    user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    # 2. Validar Dispositivo
    cursor.execute("SELECT * FROM devices WHERE id=? AND is_active=1", (request.device_id,))
    device = cursor.fetchone()
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo no autorizado o inactivo")

    # VALIDACIÓN: Bloquear usuarios eliminados
    if user["status"] == "DELETED":
        raise HTTPException(status_code=403, detail="Error: Usuario dado de baja. No autorizado para marcar asistencia.")
    
    # Validar Secuencia Lógica
    if request.action == "CLOCK_IN" and user["status"] == "ACTIVE":
        raise HTTPException(status_code=400, detail="Error: El usuario ya tiene un Check-in activo.")
    if request.action == "CLOCK_OUT" and user["status"] == "INACTIVE":
        raise HTTPException(status_code=400, detail="Error: No se puede hacer Check-out sin un Check-in previo.")
        
    server_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_status = "ACTIVE" if request.action == "CLOCK_IN" else "INACTIVE"
    last_clock_in = server_time if request.action == "CLOCK_IN" else None
        
    # 3. Guardar el registro en la tabla attendance_logs
    cursor.execute("""
        INSERT INTO attendance_logs (user_id, action, device_id, location_context, timestamp) 
        VALUES (?, ?, ?, ?, ?)
    """, (request.user_id, request.action, request.device_id, request.location_context, server_time))
    
    new_log_id = cursor.lastrowid # Obtenemos el ID autoincrementable que generó SQLite
    
    # 4. Actualizar estado del usuario en la tabla users
    cursor.execute("UPDATE users SET status=?, last_clock_in=? WHERE id=?", (new_status, last_clock_in, request.user_id))
    conn.commit()
    
    return {
        "status": "success",
        "data": {
            "log_id": new_log_id,
            "timestamp": server_time,
            "current_status": new_status
        },
        "message": f"{request.action} confirmado."
    }

@app.get("/api/v1/staff/active")
def get_active_staff():
    cursor.execute("SELECT id as user_id, name, last_clock_in as clock_in FROM users WHERE status='ACTIVE'")
    active_users = [dict(row) for row in cursor.fetchall()]
            
    return {
        "active_count": len(active_users),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": active_users
    }

@app.get("/api/v1/attendance/history/{user_id}", 
         summary="[WIP] Consultar historial del usuario",
         description="WORK IN PROGRESS: Esta ruta aún está en construcción y su estructura podría cambiar.",
         deprecated=True)
def get_user_history(user_id: str):
    cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    cursor.execute("SELECT * FROM attendance_logs WHERE user_id=?", (user_id,))
    user_logs = [dict(row) for row in cursor.fetchall()]
    return {"user_id": user_id, "total_records": len(user_logs), "logs": user_logs}

@app.get("/api/v1/staff")
def get_all_staff():
    cursor.execute("SELECT * FROM users")
    all_staff = [dict(row) for row in cursor.fetchall()]
    return {"total": len(all_staff), "staff": all_staff}

# PUT: Actualizar datos de un empleado
@app.put("/api/v1/staff/{user_id}")
def update_staff(user_id: str, request: UserUpdate):
    cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Actualización dinámica según los campos enviados
    if request.name:
        cursor.execute("UPDATE users SET name=? WHERE id=?", (request.name, user_id))
    if request.role:
        cursor.execute("UPDATE users SET role=? WHERE id=?", (request.role, user_id))
        
    conn.commit()
    
    # Devolver el usuario actualizado
    cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
    return {"message": "Usuario actualizado exitosamente", "user": dict(cursor.fetchone())}

# DELETE: Dar de baja a un empleado (Baja lógica)
@app.delete("/api/v1/staff/{user_id}")
def delete_staff(user_id: str):
    cursor.execute("UPDATE users SET status='DELETED' WHERE id=?", (user_id,))
    conn.commit()
    
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    return {"message": f"Usuario {user_id} dado de baja exitosamente"}

# POST: Agregar un nuevo empleado
@app.post("/api/v1/staff", status_code=201)
def create_staff(user: UserCreate):
    cursor.execute("SELECT id FROM users WHERE id=?", (user.id,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="El ID de usuario ya existe")
    
    cursor.execute("""
        INSERT INTO users (id, name, role, status, last_clock_in) 
        VALUES (?, ?, ?, 'INACTIVE', NULL)
    """, (user.id, user.name, user.role))
    
    conn.commit()
    
    # Devolvemos el usuario recién creado
    cursor.execute("SELECT * FROM users WHERE id=?", (user.id,))
    return {"message": "Usuario creado exitosamente", "user": dict(cursor.fetchone())}