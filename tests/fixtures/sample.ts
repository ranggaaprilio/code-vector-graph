// Sample TypeScript file with types

interface User {
  id: number;
  name: string;
  email: string;
}

/**
 * Validates a user object
 * @param user The user to validate
 * @returns True if valid, false otherwise
 */
function validateUser(user: User): boolean {
  // Check required fields
  if (!user.id || user.id <= 0) return false;
  if (!user.name || user.name.length === 0) return false;
  if (!user.email || !user.email.includes('@')) return false;
  
  return true;
}

export { validateUser };
export type { User };
