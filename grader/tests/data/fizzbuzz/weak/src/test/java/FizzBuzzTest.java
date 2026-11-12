import static org.junit.jupiter.api.Assertions.assertEquals;
import org.junit.jupiter.api.Test;
class FizzBuzzTest {
  @Test void thirdIsFizz() { assertEquals("Fizz", FizzBuzz.fizzBuzz(3).get(2)); }
}
