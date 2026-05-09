export class Outer {
    method() {
        function inner() { return 42; }
        return inner();
    }
}
