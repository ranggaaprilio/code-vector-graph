// Sample React TSX component
import React, { useState, useEffect } from 'react';

interface Props {
  initialCount?: number;
  title?: string;
}

/**
 * A simple counter component with TypeScript
 */
const Counter: React.FC<Props> = ({ initialCount = 0, title = 'Counter' }) => {
  const [count, setCount] = useState<number>(initialCount);

  useEffect(() => {
    // Log count changes
    console.log(`Count changed to: ${count}`);
  }, [count]);

  const increment = () => setCount(prev => prev + 1);
  const decrement = () => setCount(prev => prev - 1);

  return (
    <div>
      <h2>{title}</h2>
      <p>Current count: {count}</p>
      <button onClick={increment}>+</button>
      <button onClick={decrement}>-</button>
    </div>
  );
};

export default Counter;
