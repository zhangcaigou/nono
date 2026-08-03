package com.pasa.server.model;

public class ModelServiceException extends RuntimeException {
    private final String code;
    private final Object details;

    public ModelServiceException(String code, String message, Object details, Throwable cause) {
        super(message, cause);
        this.code = code;
        this.details = details;
    }

    public String getCode() {
        return code;
    }

    public Object getDetails() {
        return details;
    }
}
