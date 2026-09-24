"""Authorization dependencies for the administrative boundary."""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Reject every non-admin request at the backend boundary."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администратору",
        )
    return current_user
