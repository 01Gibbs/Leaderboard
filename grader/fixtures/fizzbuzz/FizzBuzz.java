import java.util.ArrayList;
import java.util.List;

public class FizzBuzz {

    public static List<String> fizzBuzz(int n) {
        List<String> results = new ArrayList<>();

        for (int i = 1; i <= n; i++) {
            if (i % 15 == 0) {
                results.add("FizzBuzz");
            } else if (i % 3 == 0) {
                results.add("Fizz");
            } else if (i % 5 == 0) {
                results.add("Buzz");
            } else {
                results.add(String.valueOf(i));
            }
        }

        return results;
    }

    public static void main(String[] args) {
        fizzBuzz(15).forEach(x -> System.out.println(x));
    }
    
}
