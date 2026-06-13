-- lpGBT uplink receiver state machine
-- Decodes the 64b/66b encoded lpGBT frame at 1.28 Gbps and extracts
-- 32-bit ECON-D payload words at 40 MHz (one per bunch crossing).
--
-- Reference: lpGBT Manual v1.0, CERN-ACC-2019-0054

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity lpgbt_rx is
    generic (
        G_DATA_WIDTH : integer := 32   -- usable bits per BX after overhead
    );
    port (
        -- 40 MHz recovered clock from LpGBT PLL
        clk_40      : in  std_logic;
        rst_n       : in  std_logic;

        -- Serial input from optical transceiver (oversampled, already deserialised
        -- by the FPGA MGT at 1.28 Gbps)
        rx_data     : in  std_logic_vector(31 downto 0);
        rx_valid    : in  std_logic;

        -- Decoded output (one 32-bit ECON-D word per BX)
        data_out    : out std_logic_vector(G_DATA_WIDTH-1 downto 0);
        data_valid  : out std_logic;
        frame_err   : out std_logic;  -- header sync loss
        fec_err     : out std_logic   -- uncorrectable FEC error (stub)
    );
end entity lpgbt_rx;

architecture rtl of lpgbt_rx is

    -- lpGBT frame header pattern (4 bits, sent MSB first each BX)
    constant C_HEADER_DATA : std_logic_vector(3 downto 0) := "1010";
    constant C_HEADER_IDLE : std_logic_vector(3 downto 0) := "0101";

    type t_state is (S_HUNT, S_LOCKED, S_ERROR);
    signal state       : t_state := S_HUNT;

    signal header_bits : std_logic_vector(3 downto 0);
    signal payload     : std_logic_vector(G_DATA_WIDTH-1 downto 0);
    signal lock_cnt    : unsigned(3 downto 0) := (others => '0');
    signal err_cnt     : unsigned(3 downto 0) := (others => '0');

begin

    -- Extract header nibble and 28-bit payload from the 32-bit word.
    -- lpGBT uplink: bits [31:28] = header, [27:0] = user data.
    header_bits <= rx_data(31 downto 28);
    payload     <= "0000" & rx_data(27 downto 0);

    p_fsm : process(clk_40)
    begin
        if rising_edge(clk_40) then
            data_valid <= '0';
            frame_err  <= '0';
            fec_err    <= '0';  -- FEC decoding not implemented in this stub

            if rst_n = '0' then
                state     <= S_HUNT;
                lock_cnt  <= (others => '0');
                err_cnt   <= (others => '0');
            elsif rx_valid = '1' then
                case state is

                    when S_HUNT =>
                        if header_bits = C_HEADER_DATA or
                           header_bits = C_HEADER_IDLE then
                            lock_cnt <= lock_cnt + 1;
                            if lock_cnt = 15 then
                                state    <= S_LOCKED;
                                lock_cnt <= (others => '0');
                            end if;
                        else
                            lock_cnt <= (others => '0');
                        end if;

                    when S_LOCKED =>
                        if header_bits = C_HEADER_DATA or
                           header_bits = C_HEADER_IDLE then
                            err_cnt   <= (others => '0');
                            data_out  <= payload;
                            data_valid <= '1';
                        else
                            frame_err <= '1';
                            err_cnt   <= err_cnt + 1;
                            if err_cnt = 3 then
                                state    <= S_ERROR;
                                err_cnt  <= (others => '0');
                            end if;
                        end if;

                    when S_ERROR =>
                        frame_err <= '1';
                        state     <= S_HUNT;
                        lock_cnt  <= (others => '0');

                end case;
            end if;
        end if;
    end process p_fsm;

end architecture rtl;
