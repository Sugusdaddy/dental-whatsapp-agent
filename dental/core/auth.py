"""
Sistema de autenticación multi-tenant.

Roles:
- admin: Nosotros (crear/gestionar clínicas)
- clinic: Cada clínica (ver solo sus datos)

Funcionalidad:
- Login con email/password
- JWT tokens
- Middleware de autenticación
- Admin puede crear cuentas de clínicas
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger("dental.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

MADRID_TZ = ZoneInfo("Europe/Madrid")

# ─────────────────────────────────────────────
# JWT CONFIG — estricto en producción
# ─────────────────────────────────────────────
#
# En producción (ENVIRONMENT=production) JWT_SECRET DEBE venir del entorno.
# Si no está, abortamos el arranque — usar un secret aleatorio en cada
# reinicio invalida todos los tokens existentes y rompe las sesiones de
# todos los dentistas conectados.
#
# En desarrollo/tests generamos uno aleatorio si no existe (cómodo para
# trabajar local sin tener que setear nada).

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"

_jwt_secret_env = os.getenv("JWT_SECRET")
if _jwt_secret_env:
    JWT_SECRET = _jwt_secret_env
elif IS_PRODUCTION:
    raise RuntimeError(
        "JWT_SECRET es obligatorio en producción. "
        "Genera uno con: python -c 'import secrets; print(secrets.token_hex(32))' "
        "y configúralo como variable de entorno."
    )
else:
    JWT_SECRET = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET no configurado — generado aleatorio (los tokens se "
        "invalidarán al reiniciar). Configúralo en .env para evitar esto."
    )

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 1 semana

security = HTTPBearer(auto_error=False)


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class UserRole:
    ADMIN = "admin"
    CLINIC = "clinic"


class User(BaseModel):
    """Usuario del sistema."""
    user_id: str
    email: str
    password_hash: str
    role: str  # admin | clinic
    clinic_id: Optional[str] = None  # Solo para role=clinic
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(MADRID_TZ))
    last_login: Optional[datetime] = None
    is_active: bool = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict
    expires_at: str


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str  # Nombre de la clínica
    clinic_id: Optional[str] = None  # Si no se pasa, se genera automáticamente
    address: str = Field(default="")
    phone: str = Field(default="")


class UserResponse(BaseModel):
    user_id: str
    email: str
    name: str
    role: str
    clinic_id: Optional[str]
    is_active: bool


# ─────────────────────────────────────────────
# PASSWORD HASHING
# ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash password con salt."""
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode(),
        salt.encode(),
        100000
    )
    return f"{salt}${hash_obj.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica password contra hash."""
    try:
        salt, stored_hash = password_hash.split('$')
        hash_obj = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode(),
            salt.encode(),
            100000
        )
        return hash_obj.hex() == stored_hash
    except Exception:
        return False


# ─────────────────────────────────────────────
# JWT TOKENS
# ─────────────────────────────────────────────

def create_token(user: User) -> tuple[str, datetime]:
    """Crea JWT token para usuario."""
    expires_at = datetime.now(MADRID_TZ) + timedelta(hours=JWT_EXPIRATION_HOURS)
    
    payload = {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "clinic_id": user.clinic_id,
        "exp": expires_at.timestamp(),
    }
    
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_token(token: str) -> Optional[dict]:
    """Decodifica y valida JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ─────────────────────────────────────────────
# USER REPOSITORY
# ─────────────────────────────────────────────

class UserRepository:
    """Repositorio de usuarios."""
    
    def __init__(self):
        self._users: dict[str, User] = {}
        self._email_index: dict[str, str] = {}  # email → user_id
        self._seq = 1
        
        # Crear admin por defecto
        self._create_admin()
    
    def _create_admin(self):
        """Crea usuario admin por defecto.

        En producción ADMIN_PASSWORD es obligatorio — sin él el arranque
        falla, evitando que un piloto quede expuesto con la contraseña
        por defecto 'admin123456'.
        """
        admin_email = os.getenv("ADMIN_EMAIL", "admin@dental.softlogic.ee")
        admin_password = os.getenv("ADMIN_PASSWORD")

        if not admin_password:
            if IS_PRODUCTION:
                raise RuntimeError(
                    "ADMIN_PASSWORD es obligatorio en producción. "
                    "Configura ADMIN_EMAIL y ADMIN_PASSWORD en el entorno "
                    "antes de arrancar el servidor."
                )
            admin_password = "admin123456"
            logger.warning(
                "ADMIN_PASSWORD no configurado — usando 'admin123456' (solo dev)."
            )

        admin = User(
            user_id="admin_001",
            email=admin_email,
            password_hash=hash_password(admin_password),
            role=UserRole.ADMIN,
            name="Administrador",
        )

        self._users[admin.user_id] = admin
        self._email_index[admin.email] = admin.user_id

        logger.info(f"Admin creado: {admin_email}")
    
    def create_user(
        self,
        email: str,
        password: str,
        name: str,
        clinic_id: str,
    ) -> User:
        """Crea usuario de clínica."""
        if email in self._email_index:
            raise ValueError("Email ya registrado")
        
        user_id = f"user_{self._seq:04d}"
        self._seq += 1
        
        user = User(
            user_id=user_id,
            email=email,
            password_hash=hash_password(password),
            role=UserRole.CLINIC,
            clinic_id=clinic_id,
            name=name,
        )
        
        self._users[user_id] = user
        self._email_index[email] = user_id
        
        logger.info(f"Usuario creado: {email} para clínica {clinic_id}")
        return user
    
    def get_by_email(self, email: str) -> Optional[User]:
        user_id = self._email_index.get(email)
        if user_id:
            return self._users.get(user_id)
        return None
    
    def get_by_id(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)
    
    def list_users(self) -> list[User]:
        return list(self._users.values())
    
    def update_last_login(self, user_id: str):
        user = self._users.get(user_id)
        if user:
            user.last_login = datetime.now(MADRID_TZ)
    
    def deactivate_user(self, user_id: str) -> bool:
        user = self._users.get(user_id)
        if user and user.role != UserRole.ADMIN:
            user.is_active = False
            return True
        return False


# ─────────────────────────────────────────────
# DEPENDENCIES
# ─────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Dependency para obtener usuario actual del token."""
    if not credentials:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    
    return payload


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency que requiere rol admin."""
    if user.get("role") != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Solo administradores")
    return user


async def get_clinic_id(user: dict = Depends(get_current_user)) -> str:
    """Dependency que devuelve el clinic_id del usuario."""
    if user.get("role") == UserRole.ADMIN:
        # Admin puede ver cualquier clínica (pasar como query param)
        return user.get("clinic_id") or "clinic_001"
    return user.get("clinic_id")


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(data: LoginRequest):
    """Login con email y password."""
    repo = get_user_repository()
    
    user = repo.get_by_email(data.email)
    if not user:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Cuenta desactivada")
    
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    token, expires_at = create_token(user)
    repo.update_last_login(user.user_id)
    
    return LoginResponse(
        token=token,
        user={
            "user_id": user.user_id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "clinic_id": user.clinic_id,
        },
        expires_at=expires_at.isoformat(),
    )


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Devuelve info del usuario actual."""
    return user


@router.post("/users", response_model=UserResponse)
async def create_clinic_user(
    data: CreateUserRequest,
    admin: dict = Depends(require_admin),
):
    """Crea usuario para una clínica (solo admin). También crea la clínica si no existe."""
    import secrets
    from dental.core.database import get_db
    from dental.core.models import ClinicInfo, ClinicHours
    
    repo = get_user_repository()
    db = get_db()
    
    # Generar clinic_id si no se proporciona
    clinic_id = data.clinic_id or f"clinic_{secrets.token_hex(4)}"
    
    # Crear clínica si no existe
    existing_clinic = db.get_clinic(clinic_id)
    if not existing_clinic:
        clinic = ClinicInfo(
            clinic_id=clinic_id,
            name=data.name,
            address=data.address or "Dirección pendiente",
            phone=data.phone or "+34 000 000 000",
            whatsapp_number=data.phone or "",
            hours=ClinicHours(),
            services=[],
            insurance_accepted=[],
        )
        
        # Guardar clínica en DB
        if hasattr(db, '_clinics'):
            db._clinics[clinic_id] = clinic
        
        logger.info(f"Clínica creada: {clinic_id} - {data.name}")
    
    try:
        user = repo.create_user(
            email=data.email,
            password=data.password,
            name=data.name,
            clinic_id=clinic_id,
        )
        
        return UserResponse(
            user_id=user.user_id,
            email=user.email,
            name=user.name,
            role=user.role,
            clinic_id=user.clinic_id,
            is_active=user.is_active,
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users", response_model=list[UserResponse])
async def list_users(admin: dict = Depends(require_admin)):
    """Lista todos los usuarios (solo admin)."""
    repo = get_user_repository()
    
    return [
        UserResponse(
            user_id=u.user_id,
            email=u.email,
            name=u.name,
            role=u.role,
            clinic_id=u.clinic_id,
            is_active=u.is_active,
        )
        for u in repo.list_users()
    ]


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    admin: dict = Depends(require_admin),
):
    """Desactiva un usuario (solo admin)."""
    repo = get_user_repository()
    
    if repo.deactivate_user(user_id):
        return {"status": "ok", "message": "Usuario desactivado"}
    
    raise HTTPException(status_code=404, detail="Usuario no encontrado")


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────

_user_repo: Optional[UserRepository] = None


def get_user_repository() -> UserRepository:
    global _user_repo
    if _user_repo is None:
        _user_repo = UserRepository()
    return _user_repo


# ─────────────────────────────────────────────
# CLINIC LIST ENDPOINT
# ─────────────────────────────────────────────

@router.get("/clinics")
async def list_clinics(admin: dict = Depends(require_admin)):
    """Lista todas las clínicas (solo admin)."""
    from dental.core.database import get_db
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    db = get_db()
    clinics_data = []
    MADRID = ZoneInfo("Europe/Madrid")

    # Usar los nuevos métodos que funcionan con MemoryDB y PostgresDB
    all_clinics = db.list_clinics()
    all_appointments = db.list_all_appointments()
    
    for clinic in all_clinics:
        clinic_appointments = [a for a in all_appointments if a.clinic_id == clinic.clinic_id]
        clinics_data.append({
            "clinic_id": clinic.clinic_id,
            "name": clinic.name,
            "address": clinic.address,
            "phone": clinic.phone,
            "whatsapp_number": clinic.whatsapp_number,
            "whatsapp_connected": bool(clinic.whatsapp_number),
            "total_appointments": len(clinic_appointments),
            "active_conversations": db.count_patients_by_clinic(clinic.clinic_id),
            "status": "active" if clinic.whatsapp_number else "pending",
        })

    return {"clinics": clinics_data}


@router.get("/admin/stats")
async def get_admin_stats(admin: dict = Depends(require_admin)):
    """Estadísticas globales para admin."""
    from dental.core.database import get_db
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    db = get_db()
    MADRID_TZ = ZoneInfo("Europe/Madrid")
    now = datetime.now(MADRID_TZ)
    
    # Usar los nuevos métodos que funcionan con MemoryDB y PostgresDB
    all_clinics = db.list_clinics()
    all_appointments = db.list_all_appointments()
    
    total_clinics = len(all_clinics)
    active_clinics = sum(1 for c in all_clinics if c.whatsapp_number)
    total_users = len(get_user_repository()._users)
    
    today_appointments = [a for a in all_appointments if a.appointment_datetime.date() == now.date()]
    
    # Contar conversaciones activas (pacientes totales como aproximación)
    active_conversations = sum(db.count_patients_by_clinic(c.clinic_id) for c in all_clinics)
    
    # Calcular tasa de confirmación
    confirmed = sum(1 for a in all_appointments if a.status == "confirmed")
    confirmation_rate = round((confirmed / len(all_appointments) * 100) if all_appointments else 0, 1)
    
    return {
        "total_clinics": total_clinics,
        "active_clinics": active_clinics,
        "total_users": total_users,
        "total_appointments": len(all_appointments),
        "today_appointments": len(today_appointments),
        "active_conversations": active_conversations,
        "confirmation_rate": confirmation_rate,
        "confirmed_appointments": confirmed,
        "pending_appointments": sum(1 for a in all_appointments if a.status == "pending"),
        "cancelled_appointments": sum(1 for a in all_appointments if a.status == "cancelled"),
    }


@router.get("/admin/activity")
async def get_admin_activity(admin: dict = Depends(require_admin), limit: int = 10):
    """Actividad reciente real desde la base de datos."""
    from dental.core.database import get_db
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    db = get_db()
    MADRID_TZ = ZoneInfo("Europe/Madrid")
    now = datetime.now(MADRID_TZ)
    
    activities = []
    
    # Usar los nuevos métodos que funcionan con MemoryDB y PostgresDB
    all_clinics = db.list_clinics()
    all_appointments = db.list_all_appointments()
    
    # Ordenar por fecha de cita y tomar los más recientes
    sorted_appointments = sorted(
        all_appointments, 
        key=lambda x: x.appointment_datetime, 
        reverse=True
    )[:limit]
    
    for apt in sorted_appointments:
        clinic = next((c for c in all_clinics if c.clinic_id == apt.clinic_id), None)
        clinic_name = clinic.name if clinic else apt.clinic_id
        
        # Calcular tiempo relativo desde la fecha de la cita
        apt_dt = apt.appointment_datetime
        if apt_dt.tzinfo is None:
            apt_dt = apt_dt.replace(tzinfo=MADRID_TZ)
        
        delta = now - apt_dt
        if delta.total_seconds() < 0:
            # Cita futura
            future_delta = abs(delta.total_seconds())
            if future_delta < 3600:
                time_ago = f"En {int(future_delta / 60)} min"
            elif future_delta < 86400:
                time_ago = f"En {int(future_delta / 3600)}h"
            else:
                time_ago = f"En {int(future_delta / 86400)}d"
        elif delta.total_seconds() < 60:
            time_ago = "Ahora mismo"
        elif delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() / 60)
            time_ago = f"Hace {mins} min"
        elif delta.total_seconds() < 3600:
            hours = int(delta.total_seconds() / 3600)
            time_ago = f"Hace {hours}h"
        else:
            days = int(delta.total_seconds() / 86400)
            time_ago = f"Hace {days}d"
        
        status_str = str(apt.status.value) if hasattr(apt.status, 'value') else str(apt.status)
        action = {
            "confirmed": "Cita confirmada",
            "pending": "Nueva cita pendiente",
            "cancelled": "Cita cancelada",
            "completed": "Cita completada",
            "no_show": "No se presento",
        }.get(status_str, f"Cita {status_str}")
        
        activities.append({
            "clinic_name": clinic_name,
            "action": action,
            "time_ago": time_ago,
            "timestamp": apt.appointment_datetime.isoformat(),
            "type": "appointment",
        })
    
    return {"activities": activities}
