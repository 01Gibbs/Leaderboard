package com.example.onboarding;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.httpBasic;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(properties = "spring.datasource.url=jdbc:h2:mem:testdb")
@AutoConfigureMockMvc
class EmployeeApiTests {

    @Autowired
    MockMvc mvc;

    @Test
    void createThenFetch() throws Exception {
        mvc.perform(post("/api/employees").with(httpBasic("admin", "admin123"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"asha RAO\",\"role\":\"Engineer\",\"onboardingDate\":\"2026-11-10\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").exists())
                .andExpect(jsonPath("$.name").value("Asha Rao"));

        mvc.perform(get("/api/employees").with(httpBasic("admin", "admin123")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].name").value("Asha Rao"))
                .andExpect(jsonPath("$[0].onboardingDate").value("2026-11-10"));
    }

    @Test
    void rejectsMissingFields() throws Exception {
        mvc.perform(post("/api/employees").with(httpBasic("admin", "admin123"))
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void rejectsBadDateFormat() throws Exception {
        mvc.perform(post("/api/employees").with(httpBasic("admin", "admin123"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"A\",\"role\":\"B\",\"onboardingDate\":\"10-11-2026\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void requiresAuthentication() throws Exception {
        mvc.perform(get("/api/employees")).andExpect(status().isUnauthorized());
    }
}
