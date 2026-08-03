package com.pasa.server.error;

import com.pasa.server.api.ApiModels;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(ApiException.class)
    ResponseEntity<ApiModels.ErrorResponse> api(ApiException exception, HttpServletRequest request) {
        return ResponseEntity.status(exception.status()).body(error(
                exception.code(), exception.getMessage(), exception.details(), request));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<ApiModels.ErrorResponse> validation(
            MethodArgumentNotValidException exception,
            HttpServletRequest request
    ) {
        return ResponseEntity.badRequest().body(error(
                "INVALID_REQUEST", "请求参数不合法", exception.getBindingResult().getFieldErrors(), request));
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<ApiModels.ErrorResponse> unexpected(Exception exception, HttpServletRequest request) {
        return ResponseEntity.internalServerError().body(error(
                "INTERNAL_ERROR", "服务器发生未预期错误", null, request));
    }

    private ApiModels.ErrorResponse error(String code, String message, Object details, HttpServletRequest request) {
        Object requestId = request.getAttribute(RequestIdFilter.ATTRIBUTE);
        return new ApiModels.ErrorResponse(new ApiModels.ErrorBody(
                code,
                message,
                requestId == null ? "" : requestId.toString(),
                details
        ));
    }
}
