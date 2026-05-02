// Sample JavaScript file with comments and code

/**
 * Calculates the factorial of a number
 * @param {number} n - The number to calculate factorial for
 * @returns {number} The factorial of n
 */
function factorial(n) {
  // Base case
  if (n <= 1) return 1;
  // Recursive case
  return n * factorial(n - 1);
}

// Export the function
module.exports = { factorial };
