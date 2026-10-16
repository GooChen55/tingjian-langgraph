CREATE TABLE IF NOT EXISTS listening_ops.search_outbox (
 id varchar(36) PRIMARY KEY,
 kind varchar(40) NOT NULL,
 aggregate_id bigint NULL,
 actor_id bigint NOT NULL,
 request_hash char(64) NULL,
 status varchar(20) NOT NULL DEFAULT 'PENDING',
 attempts int NOT NULL DEFAULT 0,
 lease_token varchar(36) NULL,
 lease_until datetime(6) NULL,
 next_attempt datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 published_at datetime(6) NULL,
 error_code varchar(100) NULL,
 created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 INDEX publish_due(status,next_attempt),
 INDEX lease_expiry(status,lease_until)
) ENGINE=InnoDB;
