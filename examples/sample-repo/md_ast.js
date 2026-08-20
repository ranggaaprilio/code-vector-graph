import React from 'react';
    export function sayHello() { console.log('hello'); }
    class Greeter { constructor() { } greet() { console.log(this.constructor.name); } }
    sayHello();